# TripClipper

TripClipper is a local-first MVP for preparing travel, activity, and meeting media before editing.

It scans a source folder, stores a portable project index under `projects/<project_slug>/`, calls a real model provider for Stage 2 analysis, exports CSV/Markdown/HTML reports, and can generate or apply an Eagle sync plan.

## Quick Start

```bash
python3 -m tripclipper.cli init --project-name "Japan Trip" --source-folder /path/to/media
python3 -m tripclipper.cli analyze --config projects/japan-trip/project.yaml --stage scan
python3 -m tripclipper.cli analyze --config projects/japan-trip/project.yaml --stage sample
python3 -m tripclipper.cli export --project japan-trip
python3 -m tripclipper.cli sync-eagle --project japan-trip --dry-run
```

Stage 2 requires a real OpenAI-compatible model configuration:

```yaml
model_config:
  provider: openai_compatible
  base_url: "https://api.example.com/v1"
  api_key_env: "TRIPCLIPPER_MODEL_API_KEY"
  vision_model: "vision-model-name"
  text_model: "text-model-name"
```

The API key is read from the named environment variable and is never written into `cut_index.json`, CSV, Markdown, HTML, Eagle notes, or task logs.

## Local Page

```bash
python3 -m tripclipper.cli serve --host 127.0.0.1 --port 8765
```

The page is a launcher/status panel, not a full review workstation. Review happens through the generated `review.html`, CSV files, and optional Eagle sync.
