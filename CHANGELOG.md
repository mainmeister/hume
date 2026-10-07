# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] - 2026-10-07

### Added
- Daemon mode support via `-d` / `--daemon` CLI flags and `HUE_DAEMON` environment variable for non-interactive continuous execution with graceful `SIGTERM`/`SIGINT` shutdown.
- CLI help option (`-h`, `--help`) to print usage information and exit ([88f1f54](https://github.com/mainmeister/hume/commit/88f1f54)).
- CLI listing option (`-l`, `--list`) to inspect Hue bridge configuration and exit ([3b54075](https://github.com/mainmeister/hume/commit/3b54075)).
- Safe termination mechanism for mood lighting loops with initial bulb state restoration on ESC key press ([86906df](https://github.com/mainmeister/hume/commit/86906df)).

### Changed
- Default bulb discovery to automatically filter for "Extended color light" bulbs when no bulb overrides are provided ([8953233](https://github.com/mainmeister/hume/commit/8953233)).
- Interactive mood lighting launch flow to only start upon successful bridge initialization ([b05ff38](https://github.com/mainmeister/hume/commit/b05ff38)).
