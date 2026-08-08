# JSON Parse Error Logging Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Log detailed JSON parsing error information (including line/col/char position and full text) and enhance encoding/control-character robustness in `ai_client.py`.

**Architecture:** Update `_parse_response` in `src/exif_tagger/ai_client.py` to handle `bytes` decoding, strip BOM, use `json.loads(..., strict=False)`, and log `json.JSONDecodeError` at `logger.error` level.

**Tech Stack:** Python 3.12, standard `json` and `logging` modules, `pytest`.

## Global Constraints
- Python 3.12 compatibility
- Preserves caller contract (`ValueError` re-raised `from exc` with `Response: {content[:500]}`)

---

### Task 1: Add JSON Error Logging and Encoding Safeguards in `_parse_response`

**Files:**
- Modify: `src/exif_tagger/ai_client.py:156-176`
- Test: `tests/test_ai_client.py:92-95`

**Interfaces:**
- Consumes: `json.JSONDecodeError`, `logging.Logger`, `content: str | bytes`
- Produces: `_parse_response(content: str | bytes) -> TaggingResponse`

- [ ] **Step 1: Write failing tests for JSON decode error logging and encoding safeguards**

Add tests to `tests/test_ai_client.py`:

```python
    def test_invalid_json_logs_error_and_raises_value_error(self, caplog):
        """When JSON is invalid, logger.error should record the JSONDecodeError details and attempted text."""
        import logging
        with caplog.at_level(logging.ERROR):
            with pytest.raises(ValueError, match="did not return valid JSON"):
                _parse_response("This is not JSON at all!!")

        assert "Failed to parse JSON response" in caplog.text
        assert "This is not JSON at all!!" in caplog.text

    def test_parse_response_handles_bytes_input(self):
        """_parse_response should accept bytes and decode UTF-8 correctly."""
        raw_bytes = b'{"results": [{"tag_name": "landscape", "score": 0.9}]}'
        result = _parse_response(raw_bytes)
        assert len(result.results) == 1
        assert result.results[0].tag_name == "landscape"

    def test_parse_response_handles_utf8_bom(self):
        """_parse_response should strip UTF-8 BOM if present."""
        bom_str = '\ufeff{"results": [{"tag_name": "landscape", "score": 0.9}]}'
        result = _parse_response(bom_str)
        assert len(result.results) == 1

    def test_parse_response_tolerates_unescaped_control_chars(self):
        """_parse_response should parse JSON containing unescaped control chars via strict=False."""
        control_char_str = '{"results": [{"tag_name": "landscape", "score": 0.9, "reason": "Line 1\nLine 2"}]}'
        result = _parse_response(control_char_str)
        assert len(result.results) == 1
        assert result.results[0].reason == "Line 1\nLine 2"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/projects/dev/exif-tagger/.venv/bin/pytest tests/test_ai_client.py -v`
Expected: FAIL on `test_invalid_json_logs_error_and_raises_value_error` (log message not found in caplog.text).

- [ ] **Step 3: Implement updated `_parse_response` in `src/exif_tagger/ai_client.py`**

Modify `_parse_response` in `src/exif_tagger/ai_client.py`:

```python
def _parse_response(content: str | bytes) -> TaggingResponse:
    """Parse the AI's response string into a structured TaggingResponse."""
    if isinstance(content, bytes):
        content = content.decode("utf-8", errors="replace")

    cleaned = content.strip().lstrip("\ufeff")

    # Try to extract JSON from markdown code blocks if present
    if "```" in cleaned:
        lines = cleaned.split("\n")
        json_lines = [l for l in lines[1:] if not l.startswith("```")]  # type: ignore[str-bytes-safe]
        cleaned = "\n".join(json_lines)

    # Strip any text outside the JSON object (keep first '{' to last '}')
    brace_start = cleaned.find("{")
    brace_end = cleaned.rfind("}")
    if brace_start != -1 and brace_end != -1 and brace_end > brace_start:
        cleaned = cleaned[brace_start : brace_end + 1]

    try:
        parsed = json.loads(cleaned, strict=False)
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/projects/dev/exif-tagger/.venv/bin/pytest tests/test_ai_client.py -v`
Expected: PASS

- [ ] **Step 5: Run full test suite**

Run: `/projects/dev/exif-tagger/.venv/bin/pytest`
Expected: 100% PASS

- [ ] **Step 6: Commit changes**

```bash
git add src/exif_tagger/ai_client.py tests/test_ai_client.py
git commit -m "feat(ai_client): log JSON parse errors and add encoding safeguards"
```
