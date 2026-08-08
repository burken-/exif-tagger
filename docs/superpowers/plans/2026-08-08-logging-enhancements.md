# Logging Enhancements & API Error Logging Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement configurable log levels, daily rotating file logging to `/app/logs`, secret scrubbing, and full HTTP request/response error logging for external Vision API failures.

**Architecture:** Extend Pydantic `Config` schema with `log_level` and `log_dir`, update central logging setup with `TimedRotatingFileHandler` and `SecretRedactor`, and wrap `_call_vision_api` with comprehensive request/response context capture on failure.

**Tech Stack:** Python 3.10+, `logging`, `logging.handlers.TimedRotatingFileHandler`, `pydantic`, `openai`, `pytest`.

## Global Constraints

- Do not break existing API contracts or configuration keys.
- Never log raw unredacted API keys (`sk-...`) or `Authorization` headers.
- All tests must pass with `pytest`.

---

### Task 1: Add Log Level and Log Dir to Config Schema

**Files:**
- Modify: `src/exif_tagger/models/schema.py`
- Modify: `src/exif_tagger/config.py`
- Modify: `config.yaml`
- Modify: `config.yaml.example`
- Test: `tests/test_config_logging.py`

**Interfaces:**
- Produces: `Config.log_level: str` (default `"INFO"`), `Config.log_dir: str` (default `"/app/logs"`)

- [ ] **Step 1: Write failing tests for Config log_level and log_dir**

Create `tests/test_config_logging.py`:
```python
import os
import pytest
from exif_tagger.models.schema import Config

def test_config_default_log_settings():
    cfg = Config(root_directory=".")
    assert cfg.log_level == "INFO"
    assert cfg.log_dir == "/app/logs"

def test_config_custom_log_level_uppercase():
    cfg = Config(root_directory=".", log_level="debug")
    assert cfg.log_level == "DEBUG"

def test_config_invalid_log_level():
    with pytest.raises(ValueError, match="Invalid log level"):
        Config(root_directory=".", log_level="INVALID_LEVEL")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_config_logging.py -v`
Expected: FAIL due to missing `log_level` / `log_dir` or validator on `Config`.

- [ ] **Step 3: Update `schema.py` and `config.py`**

In `src/exif_tagger/models/schema.py`:
```python
    log_level: str = Field(
        default="INFO",
        description="Global log level: DEBUG, INFO, WARNING, ERROR, CRITICAL",
    )
    log_dir: str = Field(
        default="/app/logs",
        description="Directory path for daily rotating log files",
    )

    @field_validator("log_level", mode="before")
    @classmethod
    def _validate_log_level(cls, value: str) -> str:
        if not isinstance(value, str):
            raise ValueError("log_level must be a string")
        val_upper = value.upper()
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if val_upper not in allowed:
            raise ValueError(f"Invalid log level '{value}'. Must be one of {allowed}")
        return val_upper
```

In `src/exif_tagger/config.py`, support env overrides `EXIFTAGGER_LOG_LEVEL` and `EXIFTAGGER_LOG_DIR`. Update `config.yaml` and `config.yaml.example` with `log_level: INFO` and `log_dir: /app/logs`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_config_logging.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add -f src/exif_tagger/models/schema.py src/exif_tagger/config.py config.yaml config.yaml.example tests/test_config_logging.py
git commit -m "feat: add log_level and log_dir to Config schema and environment loading"
```

---

### Task 2: Implement Rotating File Handler & Enhanced Secret Scrubbing

**Files:**
- Modify: `src/exif_tagger/ai_client.py`
- Test: `tests/test_secure_logging.py`

**Interfaces:**
- Produces: `setup_secure_logging(level: int | str = logging.INFO, log_dir: str = "/app/logs", logger_name: str = "exif_tagger") -> None`

- [ ] **Step 1: Write failing tests for setup_secure_logging & SecretRedactor**

Create `tests/test_secure_logging.py`:
```python
import logging
from pathlib import Path
from exif_tagger.ai_client import SecretRedactor, setup_secure_logging

def test_secret_redactor_scrubs_headers():
    redactor = SecretRedactor()
    record = logging.LogRecord("test", logging.ERROR, "", 0, "Authorization: Bearer sk-123456789012345678901234", (), None)
    redactor.filter(record)
    assert "sk-123456789012345678901234" not in record.getMessage()
    assert "[REDACTED]" in record.getMessage()

def test_setup_secure_logging_creates_file_handler(tmp_path):
    log_dir = str(tmp_path / "logs")
    setup_secure_logging(level="DEBUG", log_dir=log_dir, logger_name="test_logger")
    test_logger = logging.getLogger("test_logger")
    test_logger.info("Test log entry")
    
    log_file = Path(log_dir) / "exif-tagger.log"
    assert log_file.exists()
    assert "Test log entry" in log_file.read_text()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_secure_logging.py -v`
Expected: FAIL due to missing headers redactor or `log_dir` parameter in `setup_secure_logging`.

- [ ] **Step 3: Update `SecretRedactor` and `setup_secure_logging` in `ai_client.py`**

In `src/exif_tagger/ai_client.py`:
```python
from logging.handlers import TimedRotatingFileHandler

class SecretRedactor(logging.Filter):
    SECRET_PATTERNS = [
        r'sk-[a-zA-Z0-9]{20,}',
        r'api_key[=:]\s*["\']?[^\s"\']+["\']?',
        r'Bearer\s+[a-zA-Z0-9\-_]+',
        r'Authorization:\s*[^\s]+',
        r'x-api-key:\s*[^\s]+',
        r'api-key:\s*[^\s]+',
    ]
    # Redact sensitive text matching compiled patterns
```

Update `setup_secure_logging`:
```python
def setup_secure_logging(
    level: int | str = logging.INFO,
    log_dir: str = "/app/logs",
    logger_name: str = "exif_tagger",
) -> None:
    if isinstance(level, str):
        level = getattr(logging, level.upper(), logging.INFO)

    main_logger = logging.getLogger(logger_name)
    main_logger.setLevel(level)

    # Avoid duplicate handlers if already setup
    if main_logger.handlers:
        for h in main_logger.handlers:
            h.setLevel(level)
        return

    formatter = logging.Formatter(
        '%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    redactor = SecretRedactor()

    # Console Handler
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    stream_handler.addFilter(redactor)
    main_logger.addHandler(stream_handler)

    # Daily Rotating File Handler
    try:
        Path(log_dir).mkdir(parents=True, exist_ok=True)
        log_file_path = Path(log_dir) / "exif-tagger.log"
        file_handler = TimedRotatingFileHandler(
            filename=log_file_path,
            when="midnight",
            interval=1,
            backupCount=30,
            encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        file_handler.addFilter(redactor)
        main_logger.addHandler(file_handler)
    except Exception as exc:
        main_logger.warning("Could not setup file logger at %s: %s", log_dir, exc)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_secure_logging.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add -f src/exif_tagger/ai_client.py tests/test_secure_logging.py
git commit -m "feat: add daily rotating log file handler and enhance secret redactor"
```

---

### Task 3: Vision API Full Request and Response Error Logging

**Files:**
- Modify: `src/exif_tagger/ai_client.py`
- Test: `tests/test_vision_api_error_logging.py`

**Interfaces:**
- Internal `_call_vision_api()` logs full request + response block on HTTP / API error.

- [ ] **Step 1: Write failing test for external request error logging**

Create `tests/test_vision_api_error_logging.py`:
```python
import logging
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from openai import APIError
from exif_tagger.ai_client import _call_vision_api
from exif_tagger.models.schema import ModelConfig

def test_vision_api_error_logging_dumps_request_and_response(caplog, tmp_path):
    caplog.set_level(logging.ERROR)
    
    mock_response = MagicMock()
    mock_response.status_code = 400
    mock_response.headers = {"content-type": "application/json", "x-request-id": "req-123"}
    mock_response.text = '{"error": {"message": "Invalid prompt", "type": "invalid_request_error"}}'
    
    fake_error = APIError(
        message="Invalid prompt",
        request=MagicMock(url="https://api.openai.com/v1/chat/completions", headers={"Authorization": "Bearer sk-secretkey1234567890"}),
        body={"error": "Invalid prompt"}
    )
    fake_error.response = mock_response

    test_img = tmp_path / "test.jpg"
    from PIL import Image
    Image.new("RGB", (100, 100)).save(test_img)

    model_config = ModelConfig(
        base_url="https://api.openai.com/v1",
        model_name="gpt-4o",
        api_key="sk-secretkey1234567890",
    )

    with patch("openai.resources.chat.completions.Completions.create", side_effect=fake_error):
        with pytest.raises(RuntimeError, match="AI model failed"):
            _call_vision_api(model_config, test_img, "Test prompt")

    log_text = caplog.text
    assert "EXTERNAL API REQUEST ERROR" in log_text
    assert "Target URL: https://api.openai.com/v1" in log_text
    assert "HTTP Status Code: 400" in log_text
    assert "sk-secretkey1234567890" not in log_text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_vision_api_error_logging.py -v`
Expected: FAIL because `_call_vision_api` does not currently output the formatted request/response block.

- [ ] **Step 3: Implement request/response error logging block in `_call_vision_api`**

In `src/exif_tagger/ai_client.py`:
Add helper `_log_api_error(image_path: Path, attempt: int, max_retries: int, url: str, method: str, req_headers: dict, req_payload: dict, exc: Exception)`:
- Extracts response status_code, response headers, response text from `exc` (handling `openai.APIError`, `httpx.HTTPError`, etc.).
- Formats multi-line log string containing request details and response details.
- Emits log record via `logger.error()`.

Call `_log_api_error(...)` inside `_call_vision_api` exception handling block.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_vision_api_error_logging.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add -f src/exif_tagger/ai_client.py tests/test_vision_api_error_logging.py
git commit -m "feat: log full request and response details on external Vision API error"
```

---

### Task 4: Integrate Log Configuration in CLI, Server, and Audit Log Levels

**Files:**
- Modify: `src/exif_tagger/main.py`
- Modify: `src/exif_tagger/server.py`
- Modify: `src/exif_tagger/db.py`
- Modify: `src/exif_tagger/exif_writer.py`
- Test: `tests/test_main_server_logging.py`

**Interfaces:**
- CLI and Server load `config.log_level` and `config.log_dir` on startup and call `setup_secure_logging()`.

- [ ] **Step 1: Write integration test verifying CLI and Server initialize logging from Config**

Create `tests/test_main_server_logging.py`:
```python
import logging
from unittest.mock import patch
from exif_tagger.models.schema import Config
from exif_tagger.ai_client import setup_secure_logging

def test_setup_logging_from_config(tmp_path):
    log_dir = str(tmp_path / "cli_logs")
    cfg = Config(root_directory=".", log_level="DEBUG", log_dir=log_dir)
    setup_secure_logging(level=cfg.log_level, log_dir=cfg.log_dir, logger_name="exif_tagger")
    
    logger = logging.getLogger("exif_tagger")
    assert logger.level == logging.DEBUG
```

- [ ] **Step 2: Run test to verify it passes**

Run: `pytest tests/test_main_server_logging.py -v`
Expected: PASS

- [ ] **Step 3: Update `main.py` and `server.py` to use `config.log_level` and `config.log_dir`**

In `main.py`: Pass `config.log_level` (overridden to `DEBUG` if `--verbose` flag is passed) and `config.log_dir` to `setup_secure_logging()`.
In `server.py`: Initialize `setup_secure_logging()` on server startup using loaded config settings.
Audit log calls in `db.py`, `exif_writer.py`, `image_scanner.py` ensuring `DEBUG` is used for verbose queries/steps and `INFO`/`WARNING`/`ERROR` appropriately for events.

- [ ] **Step 4: Run full test suite**

Run: `pytest -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add -f src/exif_tagger/main.py src/exif_tagger/server.py src/exif_tagger/db.py src/exif_tagger/exif_writer.py tests/test_main_server_logging.py
git commit -m "feat: initialize logging from config in CLI and server, audit codebase log levels"
```
