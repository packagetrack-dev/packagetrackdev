# Changelog

All notable changes to this project are documented in this file. The format
is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

## [0.2.0] - 2026-09-14

### Changed

- The MCP server moved to its own package, [packagetrackdev-mcp](https://github.com/packagetrack-dev/packagetrackdev-mcp).
  `packagetrackdev mcp` now prints where it went and exits.

### Removed

- The `mcp` extra.

## [0.1.2] - 2026-09-13

### Changed

- `packagetrackdev mcp` suggests `claude mcp add -s user ...`, so the server is registered for every project.

## [0.1.1] - 2026-09-13

### Fixed

- `packagetrackdev mcp` run from a terminal explains that an agent starts it, instead of waiting on stdin.

## [0.1.0] - 2026-09-12

### Added

- First release: `check`, `push`, `login`, `mcp`.

[Unreleased]: https://github.com/packagetrack-dev/packagetrackdev/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/packagetrack-dev/packagetrackdev/releases/tag/v0.2.0
[0.1.2]: https://github.com/packagetrack-dev/packagetrackdev/releases/tag/v0.1.2
[0.1.1]: https://github.com/packagetrack-dev/packagetrackdev/releases/tag/v0.1.1
[0.1.0]: https://github.com/packagetrack-dev/packagetrackdev/releases/tag/v0.1.0
