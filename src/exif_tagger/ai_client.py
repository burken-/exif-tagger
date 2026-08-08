"""AI client - OpenAI-compatible vision API with batch processing."""

from __future__ import annotations

import base64
import json
import logging
from logging.handlers import TimedRotatingFileHandler
import re
import time
from pathlib import Path
from typing import Any

from openai import OpenAI
from PIL import Image

from exif_tagger.models.schema import (
    ModelConfig,
    TagDefinition,
    TaggingResponse,
    TagResult,
)

logger = logging.getLogger(__name__)


class SecretRedactor(logging.Filter):
    SECRET_PATTERNS = [
        r'sk-[a-zA-Z0-9]{20,}',
        r'api_key[=:]\s*["\']?[^\s"\']+["\']?',
        r'Bearer\s+[a-zA-Z0-9\-_]+',
        r'sk-[a-fA-F0-9]{64}',
        r'Authorization:\s*[^\s]+',
        r'x-api-key:\s*[^\s]+',
        r'api-key:\s*[^\s]+',
    ]

    def __init__(self, name: str = ""):
        super().__init__(name)
        self._compiled_patterns = [re.compile(p) for p in self.SECRET_PATTERNS]

    def filter(self, record: logging.LogRecord) -> bool:
        original_message = record.getMessage()
        redacted_message = original_message

        for pattern in self._compiled_patterns:
            redacted_message = pattern.sub('[REDACTED]', redacted_message)

        if redacted_message != original_message:
            record.msg = redacted_message
            record.args = ()  # Clear args to prevent formatting with original values

        return True


def setup_secure_logging(
    level: int | str = logging.INFO,
    log_dir: str = "/app/logs",
    logger_name: str = "exif_tagger",
) -> None:
    if isinstance(level, str):
        log_level = getattr(logging, level.upper(), logging.INFO)
    else:
        log_level = level

    main_logger = logging.getLogger(logger_name)
    main_logger.setLevel(log_level)

    if main_logger.handlers:
        for handler in main_logger.handlers:
            handler.setLevel(log_level)
        return

    formatter = logging.Formatter(
        '%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%H:%M:%S'
    )
    redactor = SecretRedactor()

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    stream_handler.addFilter(redactor)
    stream_handler.setLevel(log_level)
    main_logger.addHandler(stream_handler)

    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)
    file_handler = TimedRotatingFileHandler(
        log_path / "exif-tagger.log",
        when="midnight",
        interval=1,
        backupCount=30,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    file_handler.addFilter(redactor)
    file_handler.setLevel(log_level)
    main_logger.addHandler(file_handler)


MAX_IMAGE_DIMENSION = 1024
MAX_RETRIES = 3
RETRY_BASE_DELAY = 2.0
JPEG_QUALITY = 85


def _image_to_base64(image_path: Path, max_dim: int = MAX_IMAGE_DIMENSION) -> str:
    """Convert a local image file to base64-encoded JPEG (resized if needed)."""
    with Image.open(image_path) as img:
        if img.mode in ("RGBA", "LA", "P") or img.mode != "RGB":
            img = img.convert("RGB")

        width, height = img.size
        if max(width, height) > max_dim:
            ratio = max_dim / max(width, height)
            new_w = int(width * ratio)
            new_h = int(height * ratio)
            img = img.resize((new_w, new_h), Image.LANCZOS)

        import io

        buffer = io.BytesIO()
        img.save(buffer, format="JPEG", quality=85)
        return base64.b64encode(buffer.getvalue()).decode("utf-8")


def _build_prompt(
    tag_definitions: dict[str, TagDefinition],
    use_structured_outputs: bool = False,
) -> str:
    """Build the prompt that asks the model to evaluate all tags for one image."""
    lines = [
        "Analyze this image and assign a confidence score (0.0–1.0) for EACH of the following tags.",
        "You must include every tag in your response, even if you are not confident it applies.",
        "",
        "Tags to evaluate:",
    ]

    for name, definition in sorted(tag_definitions.items()):
        lines.append(f"- {name}: \"{definition.description}\"")

    if not use_structured_outputs:
        lines.extend([
            "",
            "Respond ONLY with valid JSON. Use this structure (no trailing commas):",
            "{",
            '  "results": [',
            '    {"tag_name": "<tag>", "score": 0.85, "reason": "<brief reason>"}',
            "  ]",
            "}",
            "",
            "Do not include any text outside of the JSON object.",
        ])

    return "\n".join(lines)


def _parse_response(content: str) -> TaggingResponse:
    """Parse the AI's response string into a structured TaggingResponse."""
    cleaned = content.strip()

    # Try to extract JSON from markdown code blocks if present
    if "```" in cleaned:
        lines = cleaned.split("\n")
        json_lines = [l for l in lines[1:] if not l.startswith("```")]  # type: ignore[str-bytes-safe]
        cleaned = "\n".join(json_lines)

    # Strip any text outside the JSON object (keep first '{' to last '}')
    brace_start = cleaned.find("{")
    brace_end = cleaned.rfind("}")
    if brace_start != -1 and brace_end != -1 and brace_end > brace_start:
        cleaned = cleaned[brace_start : brace_end + 1]

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ValueError(f"AI did not return valid JSON: {exc}\nResponse: {content[:500]}") from exc

    raw_results = parsed.get("results", [])
    tag_results = []
    for item in raw_results:
        try:
            raw_score = float(item.get("score", 0.0))
            clamped_score = max(0.0, min(1.0, raw_score))  # Clamp BEFORE pydantic validation
            tr = TagResult(
                tag_name=str(item["tag_name"]),
                score=clamped_score,
                reason=item.get("reason"),
            )
            tag_results.append(tr)
        except (KeyError, ValueError, TypeError) as exc:
            logger.warning("Skipping invalid tag result in AI response: %s", exc)

    return TaggingResponse(results=tag_results, summary=parsed.get("summary"))


def _build_structured_output_config() -> dict:
    """Build the response_format config for OpenAI structured outputs."""
    schema = TaggingResponse.model_json_schema()
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "tagging_response",
            "schema": schema,
        },
    }


def _call_vision_api(
    model_config: ModelConfig,
    image_path: Path,
    prompt: str,
    max_dim: int = MAX_IMAGE_DIMENSION,
) -> str:
    """Call the vision API with retries. Raises on persistent failure."""
    image_b64 = _image_to_base64(image_path, max_dim=max_dim)

    # Extract system_prompt and user_prompt from params if present
    params_copy = dict(model_config.params or {})
    system_prompt = params_copy.pop("system_prompt", None)
    user_prompt_extra = params_copy.pop("user_prompt", None)

    final_prompt = prompt
    if user_prompt_extra:
        final_prompt = f"{user_prompt_extra}\n\n{prompt}"

    content_parts = [
        {"type": "text", "text": final_prompt},
        {
            "type": "image_url",
            "image_url": {
                "url": f"data:image/jpeg;base64,{image_b64}",
            },
        },
    ]

    messages: list[dict[str, Any]] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": content_parts})

    # Standard OpenAI kwargs accepted by client.chat.completions.create
    known_openai_kwargs = {
        "model", "messages", "max_tokens", "temperature", "top_p", "n", "stream",
        "stop", "presence_penalty", "frequency_penalty", "logit_bias", "user",
        "response_format", "seed", "tools", "tool_choice", "reasoning_effort",
        "extra_body", "timeout", "extra_headers", "extra_query"
    }

    top_level_kwargs: dict[str, Any] = {}
    extra_body: dict[str, Any] = dict(params_copy.pop("extra_body", {}) or {})

    for k, v in params_copy.items():
        if k in known_openai_kwargs:
            top_level_kwargs[k] = v
        else:
            extra_body[k] = v

    if extra_body:
        top_level_kwargs["extra_body"] = extra_body

    kwargs: dict = {}
    if hasattr(model_config, "extra") and model_config.extra:  # type: ignore[attr-defined]
        for key, val in model_config.extra.items():  # type: ignore[union-attr]
            if key in ("timeout",):
                kwargs[key] = val

    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            client = OpenAI(
                base_url=model_config.base_url,
                api_key=model_config.api_key or "",
            )

            api_kwargs = {
                "model": model_config.model_name,
                "messages": messages,
                "max_tokens": model_config.max_tokens,
                "temperature": model_config.temperature,
                **top_level_kwargs,
            }

            # Structured outputs: guarantee valid JSON matching our schema
            if model_config.use_structured_outputs:  # type: ignore[attr-defined]
                api_kwargs["response_format"] = _build_structured_output_config()

            api_kwargs.update(kwargs)  # caller-provided kwargs still win

            response = client.chat.completions.create(**api_kwargs)
            return response.choices[0].message.content  # type: ignore[return-value]

        except Exception as exc:
            last_error = exc
            logger.warning(
                "Vision API attempt %d/%d failed for %s: %s",
                attempt, MAX_RETRIES, image_path.name, exc,
            )
            if attempt < MAX_RETRIES:
                delay = RETRY_BASE_DELAY * (2 ** (attempt - 1))
                logger.info("Retrying in %.0f seconds...", delay)
                time.sleep(delay)

    raise RuntimeError(
        f"AI model failed after {MAX_RETRIES} attempts for image "
        f"'{image_path}'. Last error: {last_error}"
    )


def tag_image_with_ai(
    model_config: ModelConfig,
    image_path: Path,
    tag_definitions: dict[str, TagDefinition],
    max_dim: int = MAX_IMAGE_DIMENSION,
) -> TaggingResponse:
    if not tag_definitions:
        logger.debug("No tags defined – skipping AI call for %s", image_path.name)
        return TaggingResponse(results=[])

    use_so = getattr(model_config, "use_structured_outputs", False)  # type: ignore[attr-defined]
    prompt = _build_prompt(tag_definitions, use_structured_outputs=use_so)

    # Call with retry logic
    raw_response = _call_vision_api(model_config, image_path, prompt, max_dim=max_dim)

    # Parse the response
    try:
        return _parse_response(raw_response)
    except ValueError as exc:
        logger.error("Failed to parse AI response for %s: %s", image_path.name, exc)
        raise

