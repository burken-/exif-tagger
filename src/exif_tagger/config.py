"""Configuration management – reads config.yaml with env var overrides."""

from __future__ import annotations

import contextlib
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

ENV_MAPPING: dict[str, tuple[str, ...]] = {
    "EXIFTAGGER_ROOT_DIRECTORY": ("root_directory",),
    "EXIFTAGGER_MODEL_BASE_URL": ("model", "base_url"),
    "EXIFTAGGER_MODEL_MODEL_NAME": ("model", "model_name"),
    "EXIFTAGGER_MODEL_API_KEY": ("model", "api_key"),
    "EXIFTAGGER_MODEL_MAX_TOKENS": ("model", "max_tokens"),
    "EXIFTAGGER_MODEL_TEMPERATURE": ("model", "temperature"),
    "EXIFTAGGER_MODEL_PARAMS": ("model", "params"),
    "EXIFTAGGER_EXCLUDE_PATTERNS": ("exclude_patterns",),
    "EXIFTAGGER_MAX_IMAGE_DIMENSION": ("max_image_dimension",),
}


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

    for env_key, keys in ENV_MAPPING.items():
        if env_key in os.environ:
            val: Any = os.environ[env_key]
            if keys[0] == "exclude_patterns" and isinstance(val, str) and not val.startswith("["):
                val = [i.strip() for i in val.split(",") if i.strip()]
            else:
                val = _cast_env_value(val)

            if len(keys) == 2:
                raw_config.setdefault(keys[0], {})[keys[1]] = val
            else:
                raw_config[keys[0]] = val

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
    with contextlib.suppress(ValueError):
        return int(value)
    with contextlib.suppress(ValueError):
        return float(value)
    if value.startswith(("[", "{")):
        with contextlib.suppress(json.JSONDecodeError, TypeError):
            parsed = json.loads(value)
            if isinstance(parsed, (list, dict)):
                return parsed
    return value


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

    tmp_path = cp_path.with_suffix(cp_path.suffix + ".tmp")

    try:
        with open(tmp_path, "w", encoding="utf-8") as fh:
            json.dump(checkpoint.model_dump(), fh, indent=2)
    except OSError:
        # Clean up temp file on write failure so we don't leave garbage
        with contextlib.suppress(OSError):
            tmp_path.unlink(missing_ok=True)
        raise

    # Atomic rename — safe even if process is killed mid-operation
    os.replace(str(tmp_path), str(cp_path))


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
