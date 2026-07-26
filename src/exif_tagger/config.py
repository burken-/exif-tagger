"""Configuration management – reads config.yaml with env var overrides."""

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

ENV_PREFIX = "EXIFTAGGER_"

DEFAULT_CONFIG_PATH = Path("config.yaml")

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
    """Validate that environment variable is in the allowed whitelist."""
    return env_key in ALLOWED_ENV_KEYS


def _env_key_to_config_key(env_key: str) -> list[str]:
    """Convert EXIFTAGGER_ROOT_DIRECTORY → ['root_directory'].

    Uses a fixed mapping for known env → config key paths. Unknown keys map to
    their lowercase snake_case form as top-level keys.
    """
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
    """Load configuration from YAML file with env-var overrides."""
    if config_path is None:
        config_file = Path(
            os.environ.get("EXIFTAGGER_CONFIG_FILE", str(DEFAULT_CONFIG_PATH))
        )
    else:
        config_file = Path(config_path)

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

    for env_key, env_value in os.environ.items():
        if env_key.startswith(ENV_PREFIX):
            if not _validate_env_key(env_key):
                logger.debug("Ignoring non-whitelisted env var: %s", env_key)
                continue
                
            config_keys = _env_key_to_config_key(env_key)

            casted_value: Any = env_value
            if len(config_keys) == 1 and config_keys[0] == "exclude_patterns":
                casted_value = _parse_list(env_value)
            else:
                casted_value = _cast_env_value(env_value)

            _set_nested(raw_config, config_keys, casted_value)

    try:
        config = Config(**raw_config)
    except Exception as exc:
        raise ValueError(f"Invalid configuration: {exc}") from exc

    return config


def _cast_env_value(value: str) -> Any:
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
    import json

    stripped = value.strip()
    if stripped.startswith("["):
        try:
            return [str(item) for item in json.loads(stripped)]
        except (json.JSONDecodeError, TypeError):
            pass
    return [item.strip() for item in stripped.split(",") if item.strip()]


def validate_path_within_base(target_path: str | Path, base_directory: str | Path) -> Path:
    target = Path(target_path).resolve()
    base = Path(base_directory).resolve()

    if not target.exists():
        raise FileNotFoundError(f"Target path does not exist: {target}")

    try:
        target.relative_to(base)
        return target
    except ValueError:
        raise ValueError(
            f"Path traversal blocked: '{target}' is outside allowed directory '{base}'"
        )


def get_checkpoint_path(root_directory: str | Path) -> Path:
    base = Path(root_directory).resolve()
    checkpoint_name = ".exif-tagger-checkpoint.json"

    candidate = base / checkpoint_name
    if candidate.parent != base:
        raise ValueError(
            f"Checkpoint path would be outside root directory: {candidate}"
        )

    return candidate


def load_checkpoint(
    root_directory: str, total_images: int
) -> dict[str, ImageCheckpoint]:
    try:
        cp_path = get_checkpoint_path(root_directory)

        validated_path = validate_path_within_base(cp_path, root_directory)
        
        if not validated_path.exists():
            return {}


        with open(validated_path, encoding="utf-8") as fh:
            data = json.load(fh)

        if data.get("version") != 1:
            return {}
        if data.get("root_directory") != str(Path(root_directory).resolve()):
            return {}
        if data.get("total_images", -1) != total_images and total_images > 0:
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
    import json
    from datetime import datetime

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
