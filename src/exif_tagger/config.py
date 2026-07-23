"""Configuration management – reads config.yaml with env var overrides.

SECURITY NOTE: This module uses yaml.safe_load() exclusively to prevent arbitrary
Python object instantiation attacks via crafted YAML files (e.g., !!python/object
payloads). Never use yaml.load() or yaml.unsafe_load() in this codebase.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC
from pathlib import Path
from typing import Any

import yaml

from exif_tagger.models.schema import Config, ImageCheckpoint

logger = logging.getLogger(__name__)

# Prefix for environment variables that override config file
ENV_PREFIX = "EXIFTAGGER_"

# Default path to config file  
DEFAULT_CONFIG_PATH = Path("config.yaml")

# Whitelist of allowed environment variable names (security)
ALLOWED_ENV_KEYS = frozenset({
    "EXIFTAGGER_CONFIG_FILE",
    "EXIFTAGGER_ROOT_DIRECTORY", 
    "EXIFTAGGER_MODEL_BASE_URL",
    "EXIFTAGGER_MODEL_MODEL_NAME",
    "EXIFTAGGER_MODEL_API_KEY",
    "EXIFTAGGER_MODEL_MAX_TOKENS",
    "EXIFTAGGER_MODEL_TEMPERATURE",
    "EXIFTAGGER_EXCLUDE_PATTERNS",
})


def _validate_env_key(env_key: str) -> bool:
    """Validate that environment variable is in the allowed whitelist.

    SECURITY: Prevents arbitrary env var injection into configuration by only
    allowing known safe environment variables to override config settings.

    Args:
        env_key: Environment variable name to validate

    Returns:
        True if the key is in the allowed whitelist
    """
    return env_key in ALLOWED_ENV_KEYS


def _env_key_to_config_key(env_key: str) -> list[str]:
    """Convert EXIFTAGGER_ROOT_DIRECTORY → ['root_directory']
       Convert EXIFTAGGER_MODEL_BASE_URL → ['model', 'base_url'].

    Uses a fixed mapping for known env → config key paths. Unknown keys map to
    their lowercase snake_case form as top-level keys.

    SECURITY: Only called after _validate_env_key() confirms the key is safe.
    """
    # Fixed mappings: env_key (lowercase after prefix) → list of YAML path segments
    _MAPPING = {
        "model_base_url": ["model", "base_url"],
        "model_model_name": ["model", "model_name"],
        "model_api_key": ["model", "api_key"],
        "model_max_tokens": ["model", "max_tokens"],
        "model_temperature": ["model", "temperature"],
        "root_directory": ["root_directory"],
        "exclude_patterns": ["exclude_patterns"],
    }

    stripped = env_key[len(ENV_PREFIX):].lower()  # type: ignore[operator]
    return _MAPPING.get(stripped, [stripped])


def _set_nested(data: dict[str, Any], keys: list[str], value: Any) -> None:
    """Set a nested dictionary value from a key path."""
    for key in keys[:-1]:
        data = data.setdefault(key, {})
    data[keys[-1]] = value


def load_config(config_path: str | Path | None = None) -> Config:
    """Load configuration from YAML file with env-var overrides.

    SECURITY NOTE: yaml.safe_load() is used exclusively to prevent arbitrary
    Python object instantiation attacks via crafted YAML files (e.g., 
    !!python/object/apply:os.system payloads). Never use yaml.load() or 
    yaml.unsafe_load() in this codebase.

    Environment variables are validated against a whitelist before being applied
    as configuration overrides, preventing injection of arbitrary settings.

    Priority (highest to lowest):
      1. Validated environment variables (EXIFTAGGER_*)
      2. Values in config.yaml (safe-loaded)
      3. Defaults defined in Pydantic models

    Args:
        config_path: Path to configuration file, or None for default location

    Returns:
        Validated Config object with all settings resolved

    Raises:
        ValueError: If YAML contains unsafe content or config is invalid
        FileNotFoundError: If specified config file doesn't exist
    """
    # Determine config file path
    if config_path is None:
        config_file = Path(
            os.environ.get("EXIFTAGGER_CONFIG_FILE", str(DEFAULT_CONFIG_PATH))
        )
    else:
        config_file = Path(config_path)

    # 1. Start with empty dict + defaults from Pydantic
    raw_config: dict[str, Any] = {}

    if config_file.exists():
        with open(config_file, encoding="utf-8") as fh:
            loaded = yaml.safe_load(fh) or {}
            if not isinstance(loaded, dict):
                raise ValueError(
                    f"config.yaml must contain a YAML mapping at the top level. "
                    f"Got: {type(loaded).__name__}"
                )
            raw_config.update(loaded)
    elif config_path is not None and str(config_file) != str(DEFAULT_CONFIG_PATH):
        raise FileNotFoundError(f"Config file not found: {config_file}")

    # 2. Override with validated environment variables (highest priority)
    for env_key, env_value in os.environ.items():
        if env_key.startswith(ENV_PREFIX):
            # SECURITY: Only process whitelisted environment variables
            if not _validate_env_key(env_key):
                logger.debug("Ignoring non-whitelisted env var: %s", env_key)
                continue
                
            config_keys = _env_key_to_config_key(env_key)

            # Cast the value appropriately based on target key
            casted_value: Any = env_value
            if len(config_keys) == 1 and config_keys[0] == "exclude_patterns":
                casted_value = _parse_list(env_value)
            else:
                casted_value = _cast_env_value(env_value)

            _set_nested(raw_config, config_keys, casted_value)

    # 3. Build Pydantic model
    try:
        config = Config(**raw_config)
    except Exception as exc:
        raise ValueError(f"Invalid configuration: {exc}") from exc

    return config


def _cast_env_value(value: str) -> Any:
    """Try to cast a string env value to bool/int/float/list."""
    if value.lower() in ("true", "yes"):
        return True
    if value.lower() in ("false", "no"):
        return False
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        pass
    # Try JSON list (e.g. '["pattern1", "pattern2"]')
    if value.startswith("["):
        import json

        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return parsed
        except (json.JSONDecodeError, TypeError):
            pass
    return value


def _parse_list(value: str) -> list[str]:
    """Parse comma-separated or JSON-list string to a list of strings."""
    import json

    stripped = value.strip()
    if stripped.startswith("["):
        try:
            return [str(item) for item in json.loads(stripped)]
        except (json.JSONDecodeError, TypeError):
            pass
    # Fall back to comma-separated
    return [item.strip() for item in stripped.split(",") if item.strip()]


# ---------------------------------------------------------------------------
# Security utilities (path validation to prevent traversal attacks)
# ---------------------------------------------------------------------------

def validate_path_within_base(target_path: str | Path, base_directory: str | Path) -> Path:
    """Validate that a target path resolves within the base directory.

    SECURITY: Prevents path traversal attacks by ensuring all file operations
    stay within intended directory boundaries. Must be used for ALL file I/O
    where user-controlled paths are involved.

    Args:
        target_path: The path to validate (file or directory)
        base_directory: The base directory that must contain the target

    Returns:
        Resolved absolute Path if valid

    Raises:
        ValueError: If path traversal attempt detected (target outside base)
        FileNotFoundError: If target path doesn't exist
    """
    target = Path(target_path).resolve()
    base = Path(base_directory).resolve()

    # Check if target exists first
    if not target.exists():
        raise FileNotFoundError(f"Target path does not exist: {target}")

    # Verify target is within base directory
    try:
        target.relative_to(base)
        return target
    except ValueError:
        raise ValueError(
            f"Path traversal blocked: '{target}' is outside allowed directory '{base}'"
        )


# ---------------------------------------------------------------------------
# Checkpoint helpers (persisted to JSON next to the config file)
# ---------------------------------------------------------------------------

def get_checkpoint_path(root_directory: str | Path) -> Path:
    """Return path where checkpoint data is stored.

    SECURITY: Ensures checkpoint file stays within root directory by using
    direct concatenation rather than user-supplied paths.

    Args:
        root_directory: The root directory for the image collection

    Returns:
        Absolute path to checkpoint file (guaranteed within root_directory)
    """
    base = Path(root_directory).resolve()
    checkpoint_name = ".exif-tagger-checkpoint.json"

    # Build candidate path - parent must equal base to prevent traversal
    candidate = base / checkpoint_name
    if candidate.parent != base:
        raise ValueError(
            f"Checkpoint path would be outside root directory: {candidate}"
        )

    return candidate


def load_checkpoint(
    root_directory: str, total_images: int
) -> dict[str, ImageCheckpoint]:
    """Load existing checkpoint if it exists and matches current run params.

    SECURITY: Validates checkpoint path before reading to prevent traversal attacks.

    Args:
        root_directory: The root directory for the image collection
        total_images: Expected number of images (for sanity check)

    Returns:
        Dict mapping absolute path strings → ImageCheckpoint objects, or empty dict
    """
    try:
        cp_path = get_checkpoint_path(root_directory)

        # SECURITY: Validate checkpoint file stays within root directory
        validated_path = validate_path_within_base(cp_path, root_directory)
        
        if not validated_path.exists():
            return {}


        with open(validated_path, encoding="utf-8") as fh:
            data = json.load(fh)

        # Basic sanity check
        if data.get("version") != 1:
            return {}
        if data.get("root_directory") != str(Path(root_directory).resolve()):
            # Different root dir → start fresh
            return {}
        if data.get("total_images", -1) != total_images and total_images > 0:
            # Image count changed (new files added?) – still use checkpoint for already-done ones
            pass

        images = data.get("images", {})
        result = {}
        for path_str, status_data in images.items():
            if isinstance(status_data, dict):
                try:
                    cp = ImageCheckpoint(**status_data)  # type: ignore[arg-type]
                    result[path_str] = cp
                except Exception:
                    continue
        return result

    except (json.JSONDecodeError, OSError, ValueError, FileNotFoundError) as exc:
        logger.debug("Checkpoint load skipped: %s", exc)
        return {}


def save_checkpoint(
    root_directory: str,
    total_images: int,
    images: dict[str, ImageCheckpoint],
) -> None:
    """Persist checkpoint data to disk.

    SECURITY: Uses validated checkpoint path from get_checkpoint_path() which
    ensures the file stays within the root directory boundary.

    Args:
        root_directory: The root directory for the image collection
        total_images: Total number of images in the collection
        images: Dict mapping absolute path strings → ImageCheckpoint objects
    """
    import json
    from datetime import datetime

    # Get validated checkpoint path (guaranteed within root_directory)
    cp_path = get_checkpoint_path(root_directory)
    processed_count = sum(
        1 for img in images.values() if img.status == "done"
    )
    from exif_tagger.models.schema import CheckpointData

    checkpoint = CheckpointData(
        version=1,
        created_at=datetime.now(UTC).isoformat(),
        root_directory=str(Path(root_directory).resolve()),
        total_images=total_images,
        processed=processed_count,
        images={k: v for k, v in images.items()},  # type: ignore[arg-type]
    )

    with open(cp_path, "w", encoding="utf-8") as fh:
        json.dump(checkpoint.model_dump(), fh, indent=2)


def get_resume_info(
    root_directory: str, total_images: int
) -> dict[str, ImageCheckpoint] | None:
    """Check if there's a checkpoint we can resume from.

    Returns checkpoint data if resumption is possible, else None.
    """
    cp = load_checkpoint(root_directory, total_images)
    done_count = sum(1 for img in cp.values() if img.status == "done")
    failed_count = sum(1 for img in cp.values() if img.status == "failed")

    if done_count > 0 or failed_count > 0:
        return cp
    return None
