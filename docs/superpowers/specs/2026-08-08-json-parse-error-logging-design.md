# Design Document: JSON Parse Error Logging in `ai_client.py`

## Overview
When the AI model returns invalid JSON (or JSON with syntax errors), `ai_client.py` currently raises a `ValueError` with a truncated snippet (`content[:500]`), but does not log the exact `JSONDecodeError` details alongside the full text being parsed. This design adds comprehensive error logging in `_parse_response` when `json.loads` fails.

## Requirements & Goals
1. Log `json.JSONDecodeError` at `logger.error` level.
2. Include the exception details (which provide line number `line X`, column `column Y`, and char position `char Z`).
3. Include the `cleaned` text that was actually passed into `json.loads()`, ensuring line/column offsets correspond directly to the logged string.
4. Include the full raw response `content` if `cleaned` differs from `content`.
5. Preserve existing caller exception contracts by re-raising `ValueError` with the `from exc` cause.
6. Verify behavior with pytest unit tests checking log output.

## Detailed Design

### 1. `_parse_response` in `src/exif_tagger/ai_client.py`

Modify the exception handler in `_parse_response`:

```python
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        if cleaned != content:
            logger.error(
                "Failed to parse JSON response: %s\nText passed to json.loads:\n%s\nRaw response:\n%s",
                exc,
                cleaned,
                content,
            )
        else:
            logger.error(
                "Failed to parse JSON response: %s\nText passed to json.loads:\n%s",
                exc,
                cleaned,
            )
        raise ValueError(f"AI did not return valid JSON: {exc}\nResponse: {content[:500]}") from exc
```

### 2. Unit Testing in `tests/test_ai_client.py`

Add a test using `caplog` to ensure:
- When invalid JSON is parsed, `logger.error` captures the error message from `json.JSONDecodeError`.
- The log message contains the text passed to `json.loads`.

## Verification Plan
- Run `/projects/dev/exif-tagger/.venv/bin/pytest tests/test_ai_client.py` to ensure all tests pass.
- Verify through log assertions that `logger.error` is triggered with the required details.
