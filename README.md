# TripClipper

TripClipper is a local-first MVP for preparing travel, activity, and meeting media before editing.

It scans a source folder, stores a portable project index under `projects/<project_slug>/`, calls a real model provider for Stage 2 analysis, exports CSV/Markdown/HTML reports, and can generate or apply an Eagle sync plan.

## Quick Start

```bash
python3 -m tripclipper.cli init --project-name "Japan Trip" --source-folder /path/to/media
python3 -m tripclipper.cli analyze --config projects/japan-trip/project.yaml --stage scan
python3 -m tripclipper.cli analyze --config projects/japan-trip/project.yaml --stage transcribe
python3 -m tripclipper.cli analyze --config projects/japan-trip/project.yaml --stage sample
python3 -m tripclipper.cli export --project japan-trip
python3 -m tripclipper.cli sync-eagle --project japan-trip --dry-run
```

Stage 2 requires a real OpenAI-compatible model configuration. Put it in a local `.env` file at the repository root, or export the same variables before starting `tripclipper serve`:

```bash
cp .env.example .env
```

Then edit `.env`:

```bash
TRIPCLIPPER_MODEL_PROVIDER=openai_compatible
TRIPCLIPPER_MODEL_BASE_URL=https://open.cherryin.ai/v1
TRIPCLIPPER_MODEL_API_KEY_ENV=TRIPCLIPPER_MODEL_API_KEY
TRIPCLIPPER_MODEL_API_KEY=replace-with-your-key
TRIPCLIPPER_VISION_MODEL=google/gemini-3.5-flash
TRIPCLIPPER_TEXT_MODEL=google/gemini-3.5-flash
TRIPCLIPPER_TRANSCRIPTION_MODEL=whisper-1
```

`transcribe` uses `ffmpeg` to extract a temporary mono 16 kHz WAV, sends it to the configured OpenAI-compatible
`/audio/transcriptions` endpoint, and writes text files under `projects/<project_slug>/cache/transcripts/`.
When `TRIPCLIPPER_TRANSCRIPTION_MODEL` is configured, `sample` and `full` analysis will also try to create missing
transcripts before calling the visual/text analysis model.

The local page does not ask for model keys. API keys stay in your local `.env` or process environment and are never written into `project.yaml`, `cut_index.json`, CSV, Markdown, HTML, Eagle notes, or task logs.

## Local Page

```bash
python3 -m tripclipper.cli serve --host 127.0.0.1 --port 8765
```

The page is a launcher/status panel, not a full review workstation. Review happens through the generated `review.html`, CSV files, and optional Eagle sync.

Project form fields are saved in browser local storage as a draft, so refreshing the page does not clear the project information you have typed.
