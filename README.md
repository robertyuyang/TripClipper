# TripClipper

TripClipper is a local-first Python tool that triages a folder of raw media and plans a rough cut, keeping `cut_index.json` as the single machine-readable source of truth.

## Status

This repository is currently at the **M0** milestone: it provides only the project skeleton, the data contract (configuration + `cut_index.json` models + field enums) and the safety boundary utilities. Scanning, model analysis, export, Eagle sync and the FastAPI page are **not** implemented yet — they are delivered by later modules (M2 / M3 / M5 / M6 / M7).

## Install

```bash
# runtime only
pip install -e .

# with development dependencies (pytest)
pip install -e ".[dev]"
```

## CLI usage

The `tripclipper` command exposes the planned sub-command surface. In M0 each
sub-command prints a placeholder message and exits cleanly (exit code 0).

```bash
tripclipper --help
tripclipper serve --host 127.0.0.1 --port 8765
tripclipper analyze --config project.yaml --stage scan
tripclipper export --project <project_slug>
tripclipper sync-eagle --project <project_slug> --dry-run
```

## Development

```bash
pytest -q
```
