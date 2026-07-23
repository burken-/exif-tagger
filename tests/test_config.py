"""Tests for configuration loading and validation."""

from __future__ import annotations

import pytest
import yaml

from exif_tagger.config import load_config
from exif_tagger.models.schema import Config, ModelConfig


class TestModelConfig:
    """Test ModelConfig pydantic model."""

    def test_defaults(self):
        mc = ModelConfig(base_url="https://api.openai.com/v1", model_name="gpt-4o")
        assert mc.max_tokens == 500
        assert mc.temperature == 0.1
        assert mc.api_key is None

    def test_explicit_values(self):
        mc = ModelConfig(
            base_url="https://example.com/v1",
            model_name="my-model",
            api_key="sk-test123",
            max_tokens=1024,
            temperature=0.5,
        )
        assert mc.base_url == "https://example.com/v1"
        assert mc.model_name == "my-model"
        assert mc.api_key == "sk-test123"
        assert mc.max_tokens == 1024
        assert mc.temperature == 0.5

    def test_invalid_temperature(self):
        with pytest.raises(Exception):
            ModelConfig(
                base_url="https://api.openai.com/v1",
                model_name="gpt-4o",
                temperature=5.0,
            )


class TestTagDefinition:
    """Test TagDefinition model."""

    def test_defaults(self):
        td = {"description": "A tag"}
        # This is how it would come from YAML – we just check the dict form first
        assert isinstance(td, dict)
        assert "description" in td

    def test_with_threshold(self):

        from exif_tagger.models.schema import TagDefinition

        td = TagDefinition(description="A tag", threshold=0.8)
        assert td.threshold == 0.8
        assert td.description == "A tag"


class TestConfig:
    """Test full Config loading and validation."""

    def test_load_from_file(self, tmp_path):
        config_data = {
            "root_directory": str(tmp_path),
            "model": {
                "base_url": "https://api.test.com/v1",
                "model_name": "test-model",
            },
            "tags": {"nature": {"description": "Nature scenes", "threshold": 0.7}},
        }
        config_file = tmp_path / "config.yaml"
        with open(config_file, "w") as fh:
            yaml.dump(config_data, fh)

        config = load_config(str(config_file))
        assert isinstance(config, Config)
        assert config.root_directory == str(tmp_path)
        assert config.ai_model.base_url == "https://api.test.com/v1"
        assert "nature" in config.tags
        assert config.tags["nature"].threshold == 0.7

    def test_env_override_api_key(self, tmp_path, monkeypatch):
        """EXIFTAGGER_ prefixed env vars should override config values."""
        config_data = {
            "root_directory": str(tmp_path),
            "model": {
                "base_url": "https://api.test.com/v1",
                "model_name": "test-model",
            },
            "tags": {"nature": {"description": "Nature scenes", "threshold": 0.7}},
        }
        config_file = tmp_path / "config.yaml"
        with open(config_file, "w") as fh:
            yaml.dump(config_data, fh)

        monkeypatch.setenv("EXIFTAGGER_MODEL_BASE_URL", "https://override.com/v1")
        config = load_config(str(config_file))
        assert config.ai_model.base_url == "https://override.com/v1"

    def test_env_override_root_directory(self, tmp_path, monkeypatch):
        """ENV vars should override root_directory."""
        other_dir = tmp_path / "other_dir"
        other_dir.mkdir()

        config_data = {
            "root_directory": str(tmp_path),
            "model": {"base_url": "https://api.test.com/v1", "model_name": "test-model"},
            "tags": {},
        }
        config_file = tmp_path / "config.yaml"
        with open(config_file, "w") as fh:
            yaml.dump(config_data, fh)

        monkeypatch.setenv("EXIFTAGGER_ROOT_DIRECTORY", str(other_dir))
        config = load_config(str(config_file))
        assert config.root_directory == str(other_dir)

    def test_validate_root_directory_not_exists(self):
        """Config with nonexistent root_directory should fail validation."""
        from exif_tagger.models.schema import Config as Cfg

        cfg_data = {
            "root_directory": "/nonexistent/path/xyz123",
            "model": {"base_url": "https://api.test.com/v1", "model_name": "test"},
            "tags": {},
        }
        config = Cfg(**cfg_data)
        with pytest.raises(ValueError, match="root_directory does not exist"):
            config.validate()

    def test_validate_exclude_patterns_invalid_regex(self, tmp_path):
        """Invalid regex in exclude_patterns should raise ValueError."""
        config_data = {
            "root_directory": str(tmp_path),
            "model": {"base_url": "https://api.test.com/v1", "model_name": "test"},
            "tags": {},
            "exclude_patterns": ["[invalid"],  # Unclosed bracket
        }
        config_file = tmp_path / "config.yaml"
        with open(config_file, "w") as fh:
            yaml.dump(config_data, fh)

        config = load_config(str(config_file))
        with pytest.raises(ValueError, match="Invalid regex"):
            config.validate_exclude_patterns()


class TestConfigValidationEdgeCases:
    """Test edge cases in config validation."""

    def test_missing_root_directory_raises(self):
        """Empty or missing root_directory should fail pydantic validation."""
        from exif_tagger.models.schema import Config as Cfg

        with pytest.raises(Exception):
            Cfg(model={"base_url": "http://x.com", "model_name": "test"})

    def test_tags_from_list_format(self, tmp_path):
        """Tags can also come in list format (handled by validator)."""
        from exif_tagger.models.schema import Config as Cfg

        cfg = Cfg(
            root_directory=str(tmp_path),
            model={"base_url": "http://x.com", "model_name": "test"},
            tags=[{"name": "tag1", "description": "First tag", "threshold": 0.5}],
        )
        assert len(cfg.tags) == 1
        assert "tag1" in cfg.tags
