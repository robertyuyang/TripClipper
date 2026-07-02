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

## CLI usage

The `tripclipper` command exposes the working project pipeline:

```bash
tripclipper --help
tripclipper init --config project.yaml
tripclipper analyze --stage scan --config project.yaml
tripclipper analyze <slug> --stage sample
tripclipper analyze <slug> --stage full
tripclipper analyze <slug> --stage cluster
tripclipper run <slug>
tripclipper export <slug>
tripclipper sync-eagle <slug> --dry-run
tripclipper sync-eagle <slug> --apply
```

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
