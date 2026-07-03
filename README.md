# TripClipper

TripClipper is a local-first Python tool that triages a folder of raw media and plans a rough cut, keeping `cut_index.json` as the single machine-readable source of truth.

## Status

This repository has implemented the local project workflow through Eagle sync:
project init, local scan, sample/full analysis, clustering, export and
`sync-eagle` are available from the CLI. The local FastAPI page (`serve`) is
still a placeholder.

## Install

```bash
# runtime only
pip install -e .

# with development dependencies (pytest)
pip install -e ".[dev]"
```

## Running the CLI

The `tripclipper` command is typically installed into the repository virtual
environment rather than your global shell environment.

Use either of these two patterns:

```bash
# option 1: activate the venv, then call tripclipper directly
source .venv/bin/activate
tripclipper --help
```

```bash
# option 2: call the venv-installed executable directly
.venv/bin/tripclipper --help
```

If `.venv` does not exist yet, a typical setup flow is:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Runtime requirements

TripClipper is now strict about local media tooling:

- `ffmpeg` and `ffprobe` are required for scan / run
- if either tool is unavailable, `tripclipper analyze --stage scan` and
  `tripclipper run` will fail immediately instead of degrading silently

On macOS, Homebrew install is usually enough:

```bash
brew install ffmpeg
```

## Common media workflows

### 1. Create a project from an existing `project.yaml`

```bash
tripclipper init --config path/to/project.yaml
```

### 2. Generate a new `project.yaml` template

```bash
tripclipper init \
  --scaffold ./project.demo.yaml \
  --project-name "Demo Project" \
  --source-folder /absolute/path/to/raw-media
```

### 3. Run the full pipeline in one command

```bash
tripclipper run <slug>
```

Current `run` behavior:

- runs `scan -> sample -> full -> cluster -> export`
- writes derived files under `projects/<slug>/exports/`
- opens `review.html` automatically at the end

### 4. Run each stage manually

```bash
tripclipper analyze --stage scan --config path/to/project.yaml
tripclipper analyze <slug> --stage sample
tripclipper analyze <slug> --stage full
tripclipper analyze <slug> --stage cluster
tripclipper export <slug>
```

Useful variants:

```bash
# scan but skip thumbnail / keyframe extraction
tripclipper analyze --stage scan --config path/to/project.yaml --no-extract-media

# full re-analyze already analyzed assets
tripclipper analyze <slug> --stage full --force

# throttle concurrent sample/full requests
tripclipper analyze <slug> --stage sample --concurrency 3
tripclipper analyze <slug> --stage full --concurrency 3

# pause after sample, inspect intermediate result, then continue
tripclipper run <slug> --pause-after sample
```

### 5. Export review artifacts only

```bash
tripclipper export <slug>
tripclipper export <slug> --cut-index-only
```

### 6. Sync to Eagle

```bash
# preview only
tripclipper sync-eagle <slug> --dry-run

# write to Eagle
tripclipper sync-eagle <slug> --apply

# incremental sync: skip already synced items
tripclipper sync-eagle <slug> --apply --skip

# retry only previously failed items
tripclipper sync-eagle <slug> --apply --retry-failed

# skip scanned-but-unanalyzed assets instead of blocking startup
tripclipper sync-eagle <slug> --apply --skip-unanalyzed

# rebuild synced Eagle items after reset confirmation
tripclipper sync-eagle <slug> --apply --reset

# same as above, but non-interactive
tripclipper sync-eagle <slug> --apply --reset --yes

# disable auto-map fallback for undeclared fields
tripclipper sync-eagle <slug> --apply --strict-mapping

# skip smart folder maintenance
tripclipper sync-eagle <slug> --apply --no-smart-folders

# guard against writing into the wrong Eagle library
tripclipper sync-eagle <slug> --apply \
  --library-path /Users/you/Pictures/MyLibrary.library
```

## CLI reference

Global help:

```bash
tripclipper --help
tripclipper --version
```

### `tripclipper init`

Create / initialize a project, or scaffold a new `project.yaml`.

```bash
tripclipper init [OPTIONS]
```

Options:

- `--config TEXT`: existing `project.yaml` path
- `--scaffold TEXT`: write a new `project.yaml` template to this path
- `--project-name TEXT`: project name; required with `--scaffold`
- `--source-folder TEXT`: media source directory; required with `--scaffold`
- `--base-dir TEXT`: override project root base directory
- `--force / --no-force`: overwrite when target already exists

### `tripclipper analyze`

Run one stage manually.

```bash
tripclipper analyze [OPTIONS] [SLUG]
```

Options:

- `--config TEXT`: `project.yaml` path; mainly used by `--stage scan`
- `--base-dir TEXT`: override project root base directory
- `--stage [scan|sample|full|cluster]`: target stage
- `--no-extract-media / --extract-media`: on `scan`, skip or enable thumbnail /
  keyframe extraction
- `--force / --no-force`: on `full`, re-run already analyzed assets
- `--concurrency INTEGER`: sample / full concurrency, default `5`

Examples:

```bash
tripclipper analyze --stage scan --config path/to/project.yaml
tripclipper analyze demo-scan --stage sample
tripclipper analyze demo-scan --stage full --force --concurrency 3
tripclipper analyze demo-scan --stage cluster
```

### `tripclipper run`

One-shot orchestration for the normal local workflow.

```bash
tripclipper run [OPTIONS] SLUG
```

Options:

- `--base-dir TEXT`: override project root base directory
- `--pause-after [sample]`: pause after sample and wait for Enter before continuing
- `--concurrency INTEGER`: sample / full concurrency, default `5`

### `tripclipper export`

Generate derived review artifacts.

```bash
tripclipper export [OPTIONS] SLUG
```

Options:

- `--base-dir TEXT`: override project root base directory
- `--cut-index-only / --no-cut-index-only`: only copy `cut_index.json`, skip
  `review.html`

Behavior:

- by default, `review.html` is generated and opened automatically
- artifacts are written under `projects/<slug>/exports/`

### `tripclipper sync-eagle`

Preview or apply Eagle synchronization.

```bash
tripclipper sync-eagle [OPTIONS] SLUG
```

Options:

- `--base-dir TEXT`: override project root base directory
- `--apply / --dry-run`: apply changes or preview only; default is `--dry-run`
- `--skip`: skip assets already marked `synced`
- `--reset`: move previously synced Eagle items to trash and clear `eagle_item_id`
- `--retry-failed`: process only assets previously marked `failed`
- `--skip-unanalyzed`: skip `scanned` assets instead of blocking startup
- `--strict-mapping`: disable `auto_map_unknown`
- `--no-smart-folders`: skip smart folder maintenance
- `--library-path TEXT`: require Eagle to have this `.library` open
- `--yes`: skip the extra confirmation used by `--reset`

### `tripclipper serve`

Start the local FastAPI launcher page. It is still a placeholder.

```bash
tripclipper serve [OPTIONS]
```

Options:

- `--host TEXT`: bind host, default `127.0.0.1`
- `--port INTEGER`: bind port, default `8765`

## Eagle sync

`sync-eagle` can guard against writing into the wrong Eagle library.

Put the expected library path in `project.yaml`:

```yaml
eagle_sync:
  api_base_url: http://localhost:41595
  library_path: /Users/you/Pictures/MyLibrary.library
```

Or pass it on the command line:

```bash
tripclipper sync-eagle <slug> --apply --library-path /Users/you/Pictures/MyLibrary.library
```

Priority is:

1. `--library-path`
2. `project.yaml.eagle_sync.library_path`
3. unset: no library-path gate

## Development

```bash
pytest -q
```
