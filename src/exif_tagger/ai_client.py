"""AI-klient – OpenAI-compatible vision API med batch-strategi B."""

from __future__ import annotations

import base64
import json
import logging
import time
from pathlib import Path

from openai import OpenAI
from PIL import Image

from exif_tagger.models.schema import (
    ModelConfig,
    TagDefinition,
    TagResult,
    TaggingResponse,
)


logger = logging.getLogger(__name__)

# Max dimensions we'll resize to before sending (keeps payload manageable)
MAX_IMAGE_DIMENSION = 1024

# Retry configuration
MAX_RETRIES = 3
RETRY_BASE_DELAY = 2.0  # seconds – exponential backoff


def _image_to_base64(image_path: Path, max_dim: int = MAX_IMAGE_DIMENSION) -> str:
    """Convert a local image file to base64-encoded JPEG (resized if needed)."""
    with Image.open(image_path) as img:
        # Convert RGBA/CMYK etc. to RGB for broad compatibility
        if img.mode in ("RGBA", "LA", "P"):
            img = img.convert("RGB")
        elif img.mode != "RGB":
            img = img.convert("RGB")

        # Resize if needed (keep aspect ratio)
        width, height = img.size
        if max(width, height) > max_dim:
            ratio = max_dim / max(width, height)
            new_w = int(width * ratio)
            new_h = int(height * ratio)
            img = img.resize((new_w, new_h), Image.LANCZOS)

        import io

        buffer = io.BytesIO()
        # JPEG quality 85 – good balance of size vs quality for AI analysis
        img.save(buffer, format="JPEG", quality=85)
        return base64.b64encode(buffer.getvalue()).decode("utf-8")


def _build_prompt(tag_definitions: dict[str, TagDefinition]) -> str:
    """Build the prompt that asks the model to evaluate all tags for one image."""
    lines = [
        "Analyze this image and determine which of the following tags apply.",
        "For each tag, provide a confidence score between 0.0 and 1.0.",
        "",
        "Tags to evaluate:",
    ]

    for name, definition in sorted(tag_definitions.items()):
        lines.append(
            f"- {name} (threshold: {definition.threshold}): \"{definition.description}\""
        )

    lines.extend([
        "",
        "Respond ONLY with valid JSON in this exact format:",
        "{",
        '  "results": [',
        '    {"tag_name": "<tag_name>", "score": <float>, "reason": "<brief reason>"},',
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

    # Parse individual results
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
) -> str:
    """Call the vision API with retries. Raises on persistent failure."""
    image_b64 = _image_to_base64(image_path)

    content_parts = [
        {"type": "text", "text": prompt},
        {
            "type": "image_url",
            "image_url": {
                "url": f"data:image/jpeg;base64,{image_b64}",
            },
        },
    ]

    # Build extra params (e.g. timeout from config)
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

            response = client.chat.completions.create(
                model=model_config.model_name,
                messages=[{"role": "user", "content": content_parts}],
                max_tokens=model_config.max_tokens,
                temperature=model_config.temperature,
                **kwargs,
            )
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
) -> TaggingResponse:
    """Tag a single image using the vision AI (batch strategy B).

    Sends one request per image with ALL configured tags included in the prompt.
    The model evaluates each tag independently and returns confidence scores.

    Args:
        model_config: Configuration for the vision API endpoint.
        image_path: Path to the local image file.
        tag_definitions: All tag definitions to evaluate against this image.

    Returns:
        Structured TaggingResponse with results, scores, and reasons.

    Raises:
        RuntimeError: If the AI model fails after MAX_RETRIES attempts.
    """
    if not tag_definitions:
        logger.debug("No tags defined – skipping AI call for %s", image_path.name)
        return TaggingResponse(results=[])

    prompt = _build_prompt(tag_definitions)

    # Call with retry logic
    raw_response = _call_vision_api(model_config, image_path, prompt)

    # Parse the response
    try:
        return _parse_response(raw_response)
    except ValueError as exc:
        logger.error("Failed to parse AI response for %s: %s", image_path.name, exc)
        raise


def tag_images_batch(
    model_config: ModelConfig,
    image_paths: list[Path],
    tag_definitions: dict[str, TagDefinition],
    verbose: bool = False,
) -> dict[Path, TaggingResponse]:
    """Tag multiple images with the vision AI.

    Args:
        model_config: Vision API configuration.
        image_paths: List of paths to process.
        tag_definitions: All configured tags.
        verbose: Whether to log per-image details during processing.

    Returns:
        Dictionary mapping each processed path → its TaggingResponse.
    """
    results: dict[Path, TaggingResponse] = {}
    total = len(image_paths)
    failed = 0

    for i, img_path in enumerate(image_paths, start=1):
        if verbose:
            logger.info("Processing image %d/%d: %s", i, total, img_path.name)

        try:
            response = tag_image_with_ai(model_config, img_path, tag_definitions)
            results[img_path] = response
            if verbose and response.results:
                matched_names = [
                    r.tag_name for r in response.results if r.score >= 0.5
                ]
                logger.info(
                    "  → %s: evaluated %d tags, scored ≥0.5: %s",
                    img_path.name, len(response.results), ", ".join(matched_names) or "(none)",
                )

        except RuntimeError as exc:
            failed += 1
            logger.error("PERMANENT FAILURE for %s – aborting run: %s", img_path.name, exc)
            # Stop the entire run on permanent failure per user requirement
            raise

    if verbose and failed > 0:
        logger.warning("Completed with %d failures out of %d images.", failed, total)

    return results
