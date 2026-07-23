# ──────────────────────────────────────────────────────────────────────────────
# EXIF-TAGGER SPEC TEMPLATE v1.0
# ──────────────────────────────────────────────────────────────────────────────
# This file is the contract between project-lead agent (spec) and coder agent (implementation).
# Coder-agent reads this spec and implements WITHOUT asking clarifying questions.

module_name: <string>                        # e.g. ai_client, exif_writer, image_scanner
version: 1                                   # Increment when spec changes (triggers re-implementation review)
priority: high|medium|low                    # For ordering feature work

summary: |
  One-paragraph description of what this module does and why it exists.

# ──────────────────────────────────────────────────────────────────────────────
# RESPONSIBILITY & BOUNDARIES
# ──────────────────────────────────────────────────────────────────────────────
responsibility: |
  What THIS module is responsible for (single responsibility).
  
not_responsible_for:                         # Explicitly OUT of scope
  - <item1>                                  # e.g. "config validation" (handled by config.py)
  - <item2>

dependencies:                                # Other modules this one depends on
  - module_name: <string>
    import_type: from|subprocess             # Python import or external tool call
    usage: <one-line description of how it's used>

# ──────────────────────────────────────────────────────────────────────────────
# PUBLIC API CONTRACT (Pydantic-style type hints)
# ──────────────────────────────────────────────────────────────────────────────
public_api:
  - function_name: <string>
    signature: |                              # Full Python type-hinted signature
      def func(param1: TypeA, param2: TypeB = default) -> ReturnType:
        """One-line docstring."""
    parameters:
      param1:
        type: TypeA
        description: "What this parameter represents and constraints"
        required: true|false
      param2:
        type: TypeB
        description: "..."
        default_value: <value>
        required: false
    returns:
      type: ReturnType
      description: |
        What the return value means.
        If tuple/dict: describe each element's position/name.
    raises:                                  # Explicit error contracts
      - exception_type: ValueError
        condition: "When this happens"
      - exception_type: RuntimeError
        condition: "When external API fails after retries"
      - exception_type: FileNotFoundError
        condition: "When image path does not exist"

# ──────────────────────────────────────────────────────────────────────────────
# ERROR HANDLING CONTRACT
# ──────────────────────────────────────────────────────────────────────────────
error_handling:
  strategy: retry|fail-fast|graceful-degrade    # Overall pattern for external calls
  
  cases:
    - scenario: "External API timeout"
      action: Retry with exponential backoff (MAX_RETRIES=3, BASE_DELAY=2s)
      after_max_retries: Raise RuntimeError with context about which image failed

    - scenario: "Invalid JSON from AI response"
      action: Log warning, return empty/structured fallback
      logging_level: WARNING

# ──────────────────────────────────────────────────────────────────────────────
# DATA FLOW (how data enters and leaves this module)
# ──────────────────────────────────────────────────────────────────────────────
data_flow:
  inputs:
    - source_module: config.py
      type: Config
      description: "Loaded configuration object"
    - source_module: image_scanner.py  
      type: list[Path]
      description: "Sorted paths to process"

  outputs:
    - destination_module: exif_writer.py
      type: dict[Path, TaggingResponse]
      description: "Mapping of processed images to their AI evaluation results"

# ──────────────────────────────────────────────────────────────────────────────
# IMPLEMENTATION CONSTRAINTS (NON-NEGOTIABLE)
# ──────────────────────────────────────────────────────────────────────────────
constraints:
  - "Use logging.getLogger(__name__) for all logs – no print() statements"
  - "All public functions must have type hints and docstrings"
  - "No side effects in pure utility functions (no file/network I/O)"
  - "Handle UTF-8 encoding explicitly when reading/writing text data"

# ──────────────────────────────────────────────────────────────────────────────
# TEST STRATEGY (coder-agent writes these, tester-agent verifies)
# ──────────────────────────────────────────────────────────────────────────────
test_strategy:
  unit_tests:                            # Must be implemented by coder-agent
    - name: "test_<function>_<scenario>"
      description: |
        What specifically is being tested.
      setup: |
        Any fixtures or mock data needed before the test runs.
      input: |
        Specific values to pass in (use tmp_path for file paths).
      expected_output:                   # Exact assertion(s)
        - "assert result == expected_value"
        - "assert len(results) >= 1"
        
  integration_tests:                     # Should verify cross-module behavior
    - name: "test_full_pipeline_flow"
      description: |
        Verify that this module's output feeds correctly into dependent modules.

# ──────────────────────────────────────────────────────────────────────────────
# EDGE CASES (must be handled or explicitly rejected)
# ──────────────────────────────────────────────────────────────────────────────
edge_cases:
  - scenario: "Empty tag_definitions dict"
    expected_behavior: Return early with empty response, skip AI call entirely
  
  - scenario: "Image file corrupted/unreadable"  
    expected_behavior: Raise ValueError with descriptive message

# ──────────────────────────────────────────────────────────────────────────────
# REVIEW CHECKLIST (for project-lead agent to verify implementation)
# ──────────────────────────────────────────────────────────────────────────────
review_checklist:
  - [ ] All public functions have type hints matching the spec signature
  - [ ] Error contracts match error_handling section exactly
  - [ ] Logging uses getLogger(__name__) and appropriate levels
  - [ ] Unit tests cover all cases in test_strategy section
  - [ ] Edge cases from edge_cases section are handled or documented
  - [ ] No print() statements (use logging instead)
