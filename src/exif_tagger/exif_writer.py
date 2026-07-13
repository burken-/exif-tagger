"""EXIF-skrivar – läser och skriver XPTags (tag 40094) via exiftool.

Använder exiftool (via subprocess) för att hantera XPTags pålitligt, då piexif
inte har inbyggt stöd för XMP/XPTags-metadata.

Fallback: Om exiftool inte finns tillgängligt, kan vi försöka med en enkel bytes-
manipulation – men det är inte rekommenderat.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path


logger = logging.getLogger(__name__)


def _check_exiftool_available() -> bool:
    """Check if exiftool is installed and accessible."""
    import shutil
    return shutil.which("exiftool") is not None


def get_existing_xptags(image_path: Path) -> set[str]:
    """Read existing XPTags from an image file using exiftool.

    Returns an empty set if the image has no EXIF/XMP or no XPTags field,
    or if exiftool is not available (graceful degradation).
    """
    if not _check_exiftool_available():
        logger.debug("exiftool not found – cannot read XPTags from %s", image_path.name)
        return set()

    try:
        result = subprocess.run(
            ["exiftool", "-s3", "-XPTags", str(image_path)],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            logger.debug("exiftool failed for %s: %s", image_path.name, result.stderr)
            return set()

        tags_str = (result.stdout or "").strip()
        if not tags_str:
            return set()

        return {t.strip().lower() for t in tags_str.split(";") if t.strip()}

    except (subprocess.TimeoutExpired, OSError, FileNotFoundError):
        logger.debug("exiftool execution failed for %s", image_path.name)
        return set()


def write_xptags(
    image_path: Path,
    new_tags_to_add: list[str],
) -> tuple[bool, int]:
    """Write new tags to the XPTags field of an image (append mode).

    Only adds tags that are NOT already present. Existing tags are left untouched.

    Args:
        image_path: Path to the image file.
        new_tags_to_add: List of tag name strings to add (if not already present).

    Returns:
        Tuple of (was_modified, number_of_new_tags_written).
    """
    if not _check_exiftool_available():
        logger.warning(
            "exiftool is required but not found. Cannot write XPTags to %s", image_path.name
        )
        return False, 0

    if not new_tags_to_add:
        return False, 0

    # Read existing tags for deduplication
    existing = get_existing_xptags(image_path)
    lower_existing = {t.lower() for t in existing}
    truly_new = [tag for tag in new_tags_to_add if tag.lower() not in lower_existing]

    if not truly_new:
        logger.debug(
            "All %d new tags already present on %s – nothing to write",
            len(new_tags_to_add), image_path.name,
        )
        return False, 0

    # Build combined tag list (existing + new) and sort for consistency
    merged = existing | {t.lower() for t in truly_new}
    tags_str = ";".join(sorted(merged))

    try:
        subprocess.run(
            ["exiftool", f"-XPTags={tags_str}", str(image_path)],
            capture_output=True, text=True, timeout=10, check=True,
        )
        logger.debug(
            "Wrote %d new XPTags to %s (total now: %d)",
            len(truly_new), image_path.name, len(merged),
        )
        return True, len(truly_new)

    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            f"Failed to write XPTags to {image_path}: exiftool error – {exc.stderr}"
        ) from exc


def tag_image_exif(
    image_path: Path,
    matched_tag_names: list[str],
) -> tuple[bool, int]:
    """Convenience wrapper that writes all matched tags to the image.

    Handles deduplication internally – only new tags are written.

    Args:
        image_path: The image file to modify.
        matched_tag_names: All tag names that should be on this image (from AI response).

    Returns:
        Tuple of (was_modified, number_of_new_tags_written).
    """
    return write_xptags(image_path, matched_tag_names)


def _parse_existing_tags(tags_str: str) -> set[str]:
    """Parse semicolon-separated tags into a deduplicated set (lowercased)."""
    if not tags_str:
        return set()
    return {t.strip().lower() for t in tags_str.split(";") if t.strip()}
