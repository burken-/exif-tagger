# Design Specification: Logging Enhancements & External API Error Logging

**Date:** 2026-08-08  
**Status:** Approved  

---

## 1. Overview

This document specifies the design for implementing standard, configurable log levels and detailed external request/response error logging across the `exif-tagger` application.

### Key Objectives
1. Add a configurable `log_level` and `log_dir` setting to the application configuration (`config.yaml`, environment variables, CLI, and Web UI).
2. Configure daily rotating file logging to `/app/logs/exif-tagger.log` alongside console logging.
3. Automatically log complete HTTP request and response details (including headers, status codes, and bodies, with sensitive authorization tokens redacted) whenever an external Vision API call encounters an error or fails.
4. Standardize log levels (`DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`) across all application components.

---

## 2. Configuration Schema Changes

### `src/exif_tagger/models/schema.py`
Add `log_level` and `log_dir` to the top-level `Config` model:

```python
class Config(BaseModel):
    root_directory: str = Field(...)
    ai_model: ModelConfig = Field(...)
    tags: dict[str, TagDefinition] = Field(...)
    exclude_patterns: list[str] = Field(...)
    max_image_dimension: int = Field(default=720, ...)
    log_level: str = Field(
        default="INFO",
        description="Global log level: DEBUG, INFO, WARNING, ERROR, CRITICAL"
    )
    log_dir: str = Field(
        default="/app/logs",
        description="Directory path for daily rotating log files"
    )
```

- **Validation**: Add `@field_validator("log_level")` to convert log level to uppercase and ensure it matches one of `("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")`.
- **Environment Variables**: Map `EXIFTAGGER_LOG_LEVEL` and `EXIFTAGGER_LOG_DIR` in configuration loaders (`config.py`).
- **Default config YAML**: Update `config.yaml` and `config.yaml.example` to include `log_level: INFO` and `log_dir: /app/logs`.

---

## 3. Centralized Logging Infrastructure

### `src/exif_tagger/ai_client.py` & `setup_secure_logging`
Update `setup_secure_logging()` to configure root/application loggers with both console and rotating file output:

1. **Handlers**:
   - `logging.StreamHandler()` writing to stdout.
   - `logging.handlers.TimedRotatingFileHandler` writing to `<log_dir>/exif-tagger.log`:
     - `when="midnight"`
     - `interval=1`
     - `backupCount=30`
     - `encoding="utf-8"`
2. **Directory Creation**: `Path(log_dir).mkdir(parents=True, exist_ok=True)` automatically creates the target folder (default `/app/logs`) if it does not exist.
3. **Secret Redacting**:
   - Enhance `SecretRedactor` to scrub:
     - API keys (`sk-...`)
     - Bearer tokens (`Bearer ...`)
     - Headers: `Authorization: ...`, `api-key: ...`, `x-api-key: ...`
     - Inline parameters `api_key=...`
   - Attach `SecretRedactor` filter to all handlers.

---

## 4. External Vision API Request & Response Error Logging

### `src/exif_tagger/ai_client.py` in `_call_vision_api()`
Wrap external OpenAI API calls with comprehensive request/response capture:

1. **Request Details Captured**:
   - Target URL (e.g. `https://api.openai.com/v1/chat/completions`)
   - HTTP Method (`POST`)
   - Request Headers (Sanitized with `SecretRedactor` / key masking)
   - Request Payload Summary (Model, Max Tokens, Temperature, System Prompt, User Prompt, Image Dimensions & Base64 Payload size)
2. **Response Details Captured on Failure**:
   - Exception type and message
   - HTTP Status Code (if available via `openai.APIError` or `httpx.HTTPStatusError`)
   - Response Headers (if available)
   - Response Body / Error text (if available)
3. **Error Log Format**:
   ```text
   ================ EXTERNAL API REQUEST ERROR ================
   Target URL: https://api.openai.com/v1/chat/completions
   HTTP Method: POST
   Image: sample.jpg (Attempt 1/3)
   Request Headers:
     Authorization: Bearer [REDACTED]
     Content-Type: application/json
   Request Payload:
     {"model": "gpt-4o", "max_tokens": 500, "temperature": 0.1, "image_size": "720x480", "prompt_len": 412}
   ---------------- HTTP RESPONSE DETAILS ----------------
   HTTP Status Code: 400 Bad Request
   Response Headers:
     date: Sat, 08 Aug 2026 14:21:00 GMT
     content-type: application/json
   Response Body:
     {"error": {"message": "Invalid image payload or unsupported format", "type": "invalid_request_error"}}
   ===========================================================
   ```

---

## 5. Codebase Log Level Standardization

- `DEBUG`: Detailed scanning steps, SQL execution, image dimension resizing, individual tag score breakdowns.
- `INFO`: Application run start/stop, image counts, server start/stop, scheduled execution triggers, progress updates.
- `WARNING`: Retriable API failures, skipped malformed individual tag results, EXIF read/write non-fatal warnings.
- `ERROR`: Vision API request/response failure blocks, AI JSON parsing failures, image tagging failures.
- `CRITICAL`: Unrecoverable database connection failures, startup configuration validation errors.

---

## 6. Testing Strategy

1. **Unit Tests**:
   - Test `SecretRedactor` filter scrubs authorization headers and API keys.
   - Test `Config` validation accepts valid log levels and rejects invalid ones.
   - Test `setup_secure_logging` initializes `TimedRotatingFileHandler` writing to specified `log_dir`.
2. **Integration Tests**:
   - Mock failing OpenAI API responses (400, 401, 500) and verify that the formatted request and response details (with headers and body) are written to the log output.
