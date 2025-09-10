# Hume Project Improvement Plan

This plan synthesizes goals and constraints from the repository’s docs/tasks.md and the provided Development Guidelines. It outlines why each change is needed, what to do, and constraints to respect. The plan is organized by theme for clarity and incremental delivery.

Constraints and context to honor throughout:
- Runtime: Python 3.12+; manage dependencies via uv with lock fidelity (uv.lock).
- Environment variables: HUE_USER_ID required at runtime; prefer HUE_BRIDGE_IP for bridge config; LOG_LEVEL optional.
- Networking: Avoid network I/O at import-time; always set timeouts; tests must be network-isolated by default.
- Testing: Use Python’s unittest; mock external calls; optional integration tests behind INTEGRATION=1.

## 1) Architecture and Entrypoint Hygiene

Rationale:
- Import-time side effects (env access, HTTP calls) break testability and tooling (linters, IDE indexers) and violate the guideline to avoid network I/O on import.

Plan:
- Move all import-time logic in main.py into functions.
- Provide a main() entrypoint that orchestrates configuration, URL building, fetch, and formatting.
- Guard runtime with `if __name__ == "__main__": main()`.

Acceptance:
- `import main` performs no network calls and does not require env variables; `uv run python main.py` executes runtime path.

## 2) Configuration Management

Rationale:
- Hard-coding BRIDGE_IP prevents portability; centralizing config simplifies testing and validation.

Plan:
- Introduce `load_config()` that reads:
  - HUE_USER_ID (required) — error with actionable message if missing when executing main().
  - HUE_BRIDGE_IP (optional; default "192.168.1.2").
  - LOG_LEVEL (optional; default INFO).
  - REQUEST_TIMEOUT (optional; default 5.0 seconds).
- Validate values and redact sensitive values in logs (only last 4 chars for HUE_USER_ID).

Acceptance:
- Running without HUE_USER_ID raises a clear, actionable error only when executing main(), not at import.

## 3) URL Composition and Networking

Rationale:
- Testable units decouple URL building and transport; timeouts prevent hangs.

Plan:
- Implement `build_base_url(user_id: str, bridge_ip: str) -> str` returning `http://{bridge_ip}/api/{user_id}/`.
- Implement `fetch_bridge_state(base_url: str, timeout: float = 5.0)` using `requests.get(..., timeout=timeout)` and returning parsed JSON data.
- Keep pretty-printing separate from fetch; return data structures.

Acceptance:
- Unit tests can validate URL composition independently; network calls always specify timeout.

## 4) Logging and Diagnostics

Rationale:
- Replace prints with configurable logging to support different environments and better operational visibility.

Plan:
- Configure logging using LOG_LEVEL with sane defaults (INFO). Use module-level logger.
- Log: startup, effective configuration (without secrets), target URL (bridge IP only), and outcomes/errors.

Acceptance:
- No print statements remain in runtime logic; logs respect LOG_LEVEL and never expose full HUE_USER_ID.

## 5) Robust Error Handling

Rationale:
- Uncaught requests or JSON errors degrade UX; actionable messages aid troubleshooting.

Plan:
- Catch `requests.exceptions.RequestException` and log error; in CLI path, exit non-zero.
- Catch JSON decoding errors and provide guidance (bridge unreachable or non-JSON response).
- Provide clear messages when HUE_USER_ID is missing.

Acceptance:
- CLI returns non-zero on failure with clear, non-sensitive diagnostics.

## 6) Testing Strategy (unittest)

Rationale:
- Ensure behavior without needing a Hue bridge; enable fast, deterministic CI.

Plan:
- Add tests/ with focused unit tests:
  - build_base_url happy-path and edge cases (IP formats).
  - load_config behavior: required/optional env vars, redaction rules.
  - fetch_bridge_state using mocked `requests.get` (success, timeout, connection error, invalid JSON).
- Provide optional integration tests guarded by `INTEGRATION=1` and skipped by default.
- Document running tests via `uv run python -m unittest discover -s tests -v`.

Acceptance:
- Unit tests pass without network; integration tests are skipped unless INTEGRATION=1.

## 7) CLI Foundation (optional initial scope)

Rationale:
- A thin CLI enables targeted operations and future extensibility while keeping entrypoint minimal.

Plan:
- Use argparse inside main(): subcommands like `state` (fetch bridge root) and `lights list` (future).
- Flags: `--bridge-ip`, `--timeout` override env.

Acceptance:
- `uv run python main.py state` prints summarized state or pretty JSON; respects overrides.

## 8) Code Quality and Typing

Rationale:
- Type hints improve readability and IDE support; lightweight tooling prevents drift.

Plan:
- Add type hints to new functions; consider `TypedDict` for responses (optional).
- Optionally add ruff and black as dev dependencies; document usage (no CI requirement initially).

Acceptance:
- mypy not required; hints present on new functions. Optional tooling documented in README.

## 9) Dependency Hygiene

Rationale:
- Keep runtime deps minimal; avoid unused imports and keep lock consistent.

Plan:
- Remove unused `huesdk.Hue` import from main.py unless used.
- Ensure pyproject declares all runtime deps; use `uv sync` to update uv.lock when needed.

Acceptance:
- No unused imports; `uv sync` works cleanly.

## 10) Packaging and Structure

Rationale:
- A small package layout prepares for growth without over-engineering.

Plan:
- Optionally introduce `hume/` package for core logic while keeping main.py as a thin CLI entrypoint.
- Consider future `pyproject [project.scripts]` entry for CLI after stabilization.

Acceptance:
- Import paths remain simple; main.py stays minimal.

## 11) Observability and UX

Rationale:
- Consistent messages and exit codes aid automation and user comprehension.

Plan:
- Standardize error messages and exit codes (0 success, 1 config error, 2 network error, etc.).
- Redact sensitive values in all outputs.

Acceptance:
- Running with misconfigurations yields clear, standardized messages.

## 12) Documentation

Rationale:
- Clear docs reduce support burden and onboarding time.

Plan:
- Add README with quickstart (uv install, env vars, running examples) and sample outputs.
- Add CONTRIBUTING.md (dev flow, tests, style) and TROUBLESHOOTING section (timeouts, missing envs, unreachable bridge).
- Provide `.env.example` (no secrets) and mention direnv or manual export.

Acceptance:
- New contributors can run the project and tests using only README.

## 13) Continuous Integration (future)

Rationale:
- CI ensures lock fidelity and prevents regressions.

Plan:
- Add a basic CI workflow that uses uv to install and run unit tests (no network access), optional lint/format jobs.

Acceptance:
- CI passes running unit tests without network.

## 14) Discovery Enhancement (future)

Rationale:
- Automatically locating the bridge simplifies first-run setup.

Plan:
- Evaluate huesdk discovery; if adopted, provide `--discover` flag and cache results, falling back to HUE_BRIDGE_IP.

Acceptance:
- Discovery optional and non-breaking; env/config overrides still respected.

---

Milestones and Order of Execution:
1) Entrypoint refactor, configuration, URL builder, fetcher, logging, and error handling (core MVP).
2) Unit tests and documentation updates (README, CONTRIBUTING, TROUBLESHOOTING).
3) Optional CLI subcommands and code quality tooling.
4) Packaging restructure (hume/ package) if needed.
5) Future CI and discovery features.

Non-Goals (for now):
- Full scene/automation management; focus on listing state and basic retrieval.
- Broad third-party integrations beyond Hue.
