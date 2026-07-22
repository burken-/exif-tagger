"""AI client - OpenAI-compatible vision API with batch processing.

SECURITY NOTE: This module includes SecretRedactor logging filter to prevent
API keys and credentials from appearing in log files. All log messages are
automatically filtered before being written to handlers.

PERFORMANCE REALITY CHECK:
Most commercial vision APIs (OpenAI GPT-4o, Claude, etc.) process images 
sequentially on their server side regardless of client concurrency settings.
This means sending multiple simultaneous requests won't speed up processing -
the API will queue them anyway. The bottleneck is the AI model's processing
time per image (~2 seconds), not our network or client code.

True parallelism only helps with:
  • Self-hosted models that truly process in parallel
  • APIs with explicit batch endpoints (multiple images in one request)
  
For most users, sequential processing (max_concurrent=1) is the right choice.
"""

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
    TagResult,
    TaggingResponse,
)


logger = logging.getLogger(__name__)

# ============================================================================
# SECURITY: Secret Redaction Logging Filter
# ============================================================================

class SecretRedactor(logging.Filter):
    """Logging filter that redacts sensitive information from log messages.

    SECURITY: Prevents API keys and credentials from appearing in log files.
    This filter intercepts all log records and redacts known secret patterns
    before they are written to handlers.
    """

    # Patterns to redact (add more as needed)
    SECRET_PATTERNS = [
        r'sk-[a-zA-Z0-9]{20,}',           # OpenAI API key format  
        r'api_key[=:]\s*["\']?[^\s"\']+["\']?',  # api_key= or api_key: patterns
        r'Bearer\s+[a-zA-Z0-9\-_]+',      # Bearer tokens
        r'sk-[a-fA-F0-9]{64}',            # Alternative API key format
    ]

    def __init__(self, name: str = ""):
        super().__init__(name)
        self._compiled_patterns = [re.compile(p) for p in self.SECRET_PATTERNS]

    def filter(self, record: logging.LogRecord) -> bool:
        """Filter log records by redacting secrets.

        Args:
            record: The log record to filter

        Returns:
            True if record should be logged (after redaction)
        """
        original_message = record.getMessage()
        redacted_message = original_message

        for pattern in self._compiled_patterns:
            redacted_message = pattern.sub('[REDACTED]', redacted_message)

        # Only modify message if something was redacted
        if redacted_message != original_message:
            record.msg = redacted_message
            record.args = ()  # Clear args to prevent formatting with original values

        return True


def setup_secure_logging(level: int = logging.INFO, logger_name: str = "exif_tagger") -> None:
    """Setup application logging with secret redaction enabled.

    SECURITY: Applies SecretRedactor filter to all log handlers to prevent
    API keys and other credentials from appearing in log files.

    Args:
        level: Logging level (DEBUG, INFO, WARNING, ERROR)
        logger_name: Name of the logger to configure
    """
    # Get or create logger
    main_logger = logging.getLogger(logger_name)
    main_logger.setLevel(level)

    # Avoid adding duplicate handlers if already configured
    if main_logger.handlers:
        return

    # Create handler and formatter
    handler = logging.StreamHandler()
    formatter = logging.Formatter(
        '%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%H:%M:%S'
    )
    handler.setFormatter(formatter)

    # Add secret redaction filter - THIS IS THE CRITICAL SECURITY STEP
    redactor = SecretRedactor()
    handler.addFilter(redactor)

    main_logger.addHandler(handler)


# ============================================================================
# PERFORMANCE: Module Constants (avoid magic numbers)
# ============================================================================

MAX_IMAGE_DIMENSION = 1024   # Max dimension for resized images  
MAX_RETRIES = 3              # Number of retry attempts for API calls
RETRY_BASE_DELAY = 2.0       # Base delay for exponential backoff (seconds)
JPEG_QUALITY = 85            # JPEG quality for base64 encoding

# CONCURRENCY NOTE: Most vision APIs (OpenAI GPT-4o, etc.) process images 
# sequentially on their server side regardless of client concurrency. Setting
# this >1 won't speed up processing and may trigger rate limits. Keep at 1
# unless you know your API provider supports true parallel image processing.
MAX_CONCURRENT_AI_CALLS = 1  # Default: sequential (most APIs queue anyway)


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


def tag_images_batch_parallel(
    model_config: ModelConfig,
    image_paths: list[Path],
    tag_definitions: dict[str, TagDefinition],
    verbose: bool = False,
    max_concurrent: int = MAX_CONCURRENT_AI_CALLS,
) -> dict[Path, TaggingResponse]:
    """Tag multiple images using concurrent AI calls.

    IMPORTANT CONCURRENCY NOTES:
    
    Most vision APIs (OpenAI GPT-4o, Claude, etc.) process images sequentially
    on their server side regardless of how many simultaneous requests you send.
    This means:
    
      • max_concurrent=1 (default): Sequential processing - recommended for most APIs
      • max_concurrent>1: May trigger rate limits without actual speedup
      
    When parallelism DOES help:
      • Self-hosted models that truly process in parallel  
      • APIs with high per-request latency but no server-side queuing
      • Batch endpoints that accept multiple images in one request
      
    When to keep max_concurrent=1:
      • OpenAI GPT-4o, Claude, most commercial vision APIs
      • APIs with strict rate limits (requests/second)
      • When you see 429 errors with concurrent requests
      
    For 100k images at ~2s per request: expect ~55 hours regardless of concurrency.
    The bottleneck is the API processing time, not our client code.

    Args:
        model_config: Vision API configuration  
        image_paths: List of paths to process
        tag_definitions: All configured tags
        verbose: Whether to log per-image details
        max_concurrent: Maximum concurrent API calls (1=default for most APIs)
        
    Returns:
        Dictionary mapping each processed path → its TaggingResponse
        
    Raises:
        RuntimeError: If any image fails after all retries (stops the batch)
    """
    results: dict[Path, TaggingResponse] = {}
    total = len(image_paths)
    
    if verbose:
        logger.info("Starting parallel AI processing (%d concurrent workers)", max_concurrent)

    with ThreadPoolExecutor(max_workers=max_concurrent) as executor:
        # Submit all tasks
        futures = {
            executor.submit(
                tag_image_with_ai, model_config, img_path, tag_definitions
            ): img_path
            for img_path in image_paths
        }

        # Process completed tasks as they finish  
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
    """Tag multiple images with the vision AI.

    PERFORMANCE REALITY CHECK:
    
    This function processes images sequentially by default (max_concurrent=1).
    Most commercial vision APIs process images one at a time on their servers,
    so increasing concurrency typically won't speed things up and may trigger
    rate limits.
    
    For true parallelism, you need either:
      1. A self-hosted model that processes multiple requests simultaneously
      2. An API with explicit batch endpoints (not just concurrent requests)
      3. Multiple API keys/accounts to distribute load
      
    Typical processing time: ~2 seconds per image regardless of concurrency setting.

    Args:
        model_config: Vision API configuration.
        image_paths: List of paths to process.
        tag_definitions: All configured tags.
        verbose: Whether to log per-image details during processing.

    Returns:
        Dictionary mapping each processed path → its TaggingResponse.
    """
    return tag_images_batch_parallel(
        model_config=model_config,
        image_paths=image_paths,
        tag_definitions=tag_definitions,
        verbose=verbose,
        max_concurrent=MAX_CONCURRENT_AI_CALLS,  # Defaults to 1 (sequential)
    )
