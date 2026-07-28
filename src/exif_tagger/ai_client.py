"""AI client - OpenAI-compatible vision API with batch processing."""

from __future__ import annotations

import base64
import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

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


def setup_secure_logging(level: int = logging.INFO, logger_name: str = "exif_tagger") -> None:
    main_logger = logging.getLogger(logger_name)
    main_logger.setLevel(level)

    if main_logger.handlers:
        return

    handler = logging.StreamHandler()
    formatter = logging.Formatter(
        '%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%H:%M:%S'
    )
    handler.setFormatter(formatter)

    redactor = SecretRedactor()
    handler.addFilter(redactor)

    main_logger.addHandler(handler)


MAX_IMAGE_DIMENSION = 1024
MAX_RETRIES = 3
RETRY_BASE_DELAY = 2.0
JPEG_QUALITY = 85

MAX_CONCURRENT_AI_CALLS = 1


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


def _build_prompt(tag_definitions: dict[str, TagDefinition]) -> str:
    """Build the prompt that asks the model to evaluate all tags for one image."""
    lines = [
        "Analyze this image and assign a confidence score (0.0–1.0) for EACH of the following tags.",
        "You must include every tag in your response, even if you are not confident it applies.",
        "",
        "Tags to evaluate:",
    ]

    for name, definition in sorted(tag_definitions.items()):
        lines.append(f"- {name}: \"{definition.description}\"")

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
    # Try to extract JSON from markdown code blocks if present
    cleaned = content.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        json_lines = [l for l in lines[1:] if not l.startswith("```")]  # type: ignore[str-bytes-safe]
        cleaned = "\n".join(json_lines)

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


def _call_vision_api(
    model_config: ModelConfig,
    image_path: Path,
    prompt: str,
    max_dim: int = MAX_IMAGE_DIMENSION,
) -> str:
    """Call the vision API with retries. Raises on persistent failure."""
    image_b64 = _image_to_base64(image_path, max_dim=max_dim)

    content_parts = [
        {"type": "text", "text": prompt},
        {
            "type": "image_url",
            "image_url": {
                "url": f"data:image/jpeg;base64,{image_b64}",
            },
        },
    ]

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

            # Merge extra params with explicit fields taking priority
            api_kwargs = {**model_config.params}
            api_kwargs.update({
                "model": model_config.model_name,
                "messages": [{"role": "user", "content": content_parts}],
                "max_tokens": model_config.max_tokens,
                "temperature": model_config.temperature,
            })
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

    prompt = _build_prompt(tag_definitions)

    # Call with retry logic
    raw_response = _call_vision_api(model_config, image_path, prompt, max_dim=max_dim)

    # Parse the response
    try:
        return _parse_response(raw_response)
    except ValueError as exc:
        logger.error("Failed to parse AI response for %s: %s", image_path.name, exc)
        raise


def tag_images_batch_parallel(
    model_config: ModelConfig,
    image_paths: list[Path],
    tag_definitions: dict[str, TagDefinition],
    verbose: bool = False,
    max_concurrent: int = MAX_CONCURRENT_AI_CALLS,
) -> dict[Path, TaggingResponse]:
    results: dict[Path, TaggingResponse] = {}
    total = len(image_paths)
    
    if verbose:
        logger.info("Starting parallel AI processing (%d concurrent workers)", max_concurrent)

    with ThreadPoolExecutor(max_workers=max_concurrent) as executor:
        futures = {
            executor.submit(
                tag_image_with_ai, model_config, img_path, tag_definitions
            ): img_path
            for img_path in image_paths
        }

        for i, future in enumerate(as_completed(futures), start=1):
            img_path = futures[future]

            if verbose:
                logger.info("Processing image %d/%d: %s", i, total, img_path.name)

            try:
                response = future.result()  # This will raise if exception occurred
                results[img_path] = response
                
                if verbose and response.results:
                    matched_names = [r.tag_name for r in response.results if r.score >= 0.5]
                    logger.info(
                        "  → %s: evaluated %d tags, scored ≥0.5: %s",
                        img_path.name, len(response.results), ", ".join(matched_names) or "(none)",
                    )

            except RuntimeError as exc:
                logger.error("PERMANENT FAILURE for %s – aborting batch: %s", img_path.name, exc)
                raise  # Stop the entire run on permanent failure
    
    if verbose:
        logger.info("Parallel AI processing complete (%d images)", len(results))

    return results


def tag_images_batch(
    model_config: ModelConfig,
    image_paths: list[Path],
    tag_definitions: dict[str, TagDefinition],
    verbose: bool = False,
) -> dict[Path, TaggingResponse]:
    return tag_images_batch_parallel(
        model_config=model_config,
        image_paths=image_paths,
        tag_definitions=tag_definitions,
        verbose=verbose,
        max_concurrent=MAX_CONCURRENT_AI_CALLS,  # Defaults to 1 (sequential)
    )
