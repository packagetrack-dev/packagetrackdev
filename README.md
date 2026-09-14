# packagetrackdev

[![CI](https://github.com/packagetrack-dev/packagetrackdev/actions/workflows/ci.yml/badge.svg)](https://github.com/packagetrack-dev/packagetrackdev/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

Command-line client for [PackageTrack](https://packagetrack.dev). Reads the
lock file in a project and reports which dependencies are behind, which
installed versions have been withdrawn, and what the release notes in
between say.

Supported lock files: `package-lock.json`, `uv.lock`, `poetry.lock`,
`Cargo.lock`, `composer.lock`, `go.mod`. Falls back to `requirements.txt` or
`package.json` when there is no lock file.

## Install

```sh
curl -fsSL https://packagetrack.dev/install.sh | sh
```

Installs `uv` if needed, then this package and
[packagetrackdev-mcp](https://github.com/packagetrack-dev/packagetrackdev-mcp)
as `uv` tools. No root required. To install only the CLI:

```sh
uv tool install "packagetrackdev @ https://packagetrack.dev/cli/packagetrackdev-latest.whl"
```

Requires Python 3.11+.

## Usage

```sh
packagetrackdev check                  # report on the current directory, no account needed
packagetrackdev push --name my-app     # upload the dependency set to your dashboard
packagetrackdev login --api-key pkgt_...
```

Common options:

| Option | Description |
|---|---|
| `--project DIR` | Directory to read. Default: current directory. |
| `--ecosystem pypi\|npm` | Read only one lock file type. |
| `--server URL` | PackageTrack server. Default: `https://packagetrack.dev`. |
| `--dry-run` | Print the request payload and send nothing. |
| `--all` | `check` only: also list packages the archive does not hold. |

`push` needs an API key, from `packagetrackdev login`, the
`PACKAGETRACK_API_KEY` environment variable, or `--api-key`.

## What is sent

Package names and versions, and for `push`, which package required which.
No source code, file paths or repository name. `--dry-run` prints the exact
payload.

## Coding agents

The archive is also available to Claude Code, Cursor and other MCP clients
through [packagetrackdev-mcp](https://github.com/packagetrack-dev/packagetrackdev-mcp):

```sh
claude mcp add -s user packagetrackdev -- packagetrackdev-mcp
```

## Development

```sh
uv sync
uv run pytest
```

## License

MIT
