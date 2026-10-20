# Changelog

All notable changes to this project are documented in this file. The format
is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

## [0.3.1] - 2026-10-20

### Changed

- `push` says when it made a new project and how many dependencies it could not compare, instead of "0 behind".

### Fixed

- A UTF-16 file (PowerShell's `pip freeze > requirements.txt`) or a UTF-8 file with a BOM is read; the first requirement is no longer dropped.
- A lock file of an unexpected shape is refused with a message instead of crashing.
- `requirements.txt`: `a===1.0` keeps its version, and `a==1.0,<2` or `a==1.*` is a range, not a version. A hash continuation line no longer joins the version.
- npm workspaces are read as the project: their folders are no longer dependencies, and their own dependencies count as declared.
- npm edges resolve the way Node does, so a nested copy of a package keeps its own parent and version.
- `Cargo.lock` and `uv.lock` keep every version of a package (`syn` 1 beside `syn` 2, a package forked by marker).
- A Go SBOM (`pkg:golang/...`) is read as the go ecosystem instead of being refused.
- The package an SBOM describes is no longer listed as its own dependency, and SPDX `*_DEPENDENCY_OF` relations are read.

## [0.3.0] - 2026-10-13

### Added

- `check` lists deprecated versions under their own heading, after withdrawn ones.

### Changed

- `check` gives every requested package its own result: compared, unknown, unpinned, a version the registry never published, or not answered.
  Two installed versions of one package no longer collapse into one.

### Fixed

- A requirements line counts only when the whole line is one: `SECRET_KEY=...`, a wheel URL or a Windows path is no longer read as a dependency.
- A dependency name shaped like an access token or API key is never sent; it is counted as skipped.
- An exact version in package.json (`7.29.0`) is read as the pin npm treats it as, not as unpinned.
- A withdrawal reason keeps its link instead of losing it as a changelog trailer.
- Release excerpts drop reStructuredText anchors and link labels, and no longer end on a bare heading.

## [0.2.2] - 2026-09-17

### Fixed

- `--ecosystem` accepts every ecosystem the lock readers know (cargo, composer, go, npm, pypi), not only pypi and npm.

## [0.2.1] - 2026-09-15

### Fixed

- The documented `uv tool install` line now works: it uses `--find-links https://packagetrack.dev/cli/`.
  A `...-latest.whl` URL is rejected by uv before the request is made.

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

[Unreleased]: https://github.com/packagetrack-dev/packagetrackdev/compare/v0.3.1...HEAD
[0.3.1]: https://github.com/packagetrack-dev/packagetrackdev/releases/tag/v0.3.1
[0.3.0]: https://github.com/packagetrack-dev/packagetrackdev/releases/tag/v0.3.0
[0.2.2]: https://github.com/packagetrack-dev/packagetrackdev/releases/tag/v0.2.2
[0.2.1]: https://github.com/packagetrack-dev/packagetrackdev/releases/tag/v0.2.1
[0.2.0]: https://github.com/packagetrack-dev/packagetrackdev/releases/tag/v0.2.0
[0.1.2]: https://github.com/packagetrack-dev/packagetrackdev/releases/tag/v0.1.2
[0.1.1]: https://github.com/packagetrack-dev/packagetrackdev/releases/tag/v0.1.1
[0.1.0]: https://github.com/packagetrack-dev/packagetrackdev/releases/tag/v0.1.0
