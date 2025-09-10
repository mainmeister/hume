# Contributing to hume

Thanks for your interest in contributing! This project aims to be a minimal, testable Philips Hue control utility.

## Environment and Tooling

- Python: 3.12+
- Dependency manager: [uv](https://docs.astral.sh/uv/)
- Locked dependencies are tracked in `uv.lock`.

Quick setup:

```bash
# Install uv if needed
# Linux/macOS:
curl -LsSf https://astral.sh/uv/install.sh | sh
# Windows (PowerShell):
iwr https://astral.sh/uv/install.ps1 -UseBasicParsing | iex

# Install dependencies
uv sync
```

## Running

```bash
# Required at runtime
export HUE_USER_ID="<your-registered-user-id>"

# Optional
export HUE_BRIDGE_IP="192.168.1.2"
export LOG_LEVEL="INFO"
export REQUEST_TIMEOUT="5"

uv run python main.py
```

## Testing

This project uses Python’s built-in `unittest`.

```bash
uv run python -m unittest discover -s tests -v
```

- Integration tests (if any) are skipped by default.
- Enable them only when you have a reachable Hue Bridge:

```bash
INTEGRATION=1 uv run python -m unittest discover -s tests -v
```

## Style and Conventions

- Avoid side-effects at import time; gate runtime under `if __name__ == "__main__":`.
- Always set timeouts on HTTP requests.
- Use the standard `logging` module; respect the `LOG_LEVEL` env var.
- Handle errors gracefully (`requests.exceptions.RequestException`, JSON decoding errors) with actionable messages.
- Redact sensitive values in logs (never print the full `HUE_USER_ID`).
- Prefer small, isolated units; mock external calls in tests.

## Dependency Hygiene

- Keep runtime dependencies declared in `pyproject.toml` and in sync with `uv.lock` (`uv sync`).
- Remove unused imports.

## Submitting Changes

1. Create a feature branch.
2. Make minimal, focused changes.
3. Add/update tests as appropriate.
4. Update documentation (README, docs/tasks.md checkboxes) if relevant.
5. Open a pull request describing the change and how to verify it.
