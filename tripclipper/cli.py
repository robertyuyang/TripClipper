from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .analyzer import analyze_project
from .config import create_project_config
from .eagle import eagle_apply, eagle_dry_run
from .exporter import export_project


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = args.func(args)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    if result is not None:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tripclipper", description="TripClipper local media preparation agent")
    subcommands = parser.add_subparsers(dest="command", required=True)

    init = subcommands.add_parser("init", help="create projects/<slug>/project.yaml")
    init.add_argument("--project-name", required=True)
    init.add_argument("--source-folder", required=True)
    init.add_argument("--output-style", default="travel_vlog")
    init.add_argument("--target-length", default="3min")
    init.add_argument("--audience", default="friends")
    init.add_argument("--people-focus", default="medium")
    init.add_argument("--audio-priority", default="medium")
    init.add_argument("--model-provider", default="openai_compatible")
    init.add_argument("--model-base-url")
    init.add_argument("--api-key-env", default="TRIPCLIPPER_MODEL_API_KEY")
    init.add_argument("--vision-model")
    init.add_argument("--text-model")
    init.add_argument("--transcription-model")
    init.add_argument("--sample-size", type=int, default=25)
    init.set_defaults(func=_cmd_init)

    serve = subcommands.add_parser("serve", help="start local FastAPI launcher")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    serve.set_defaults(func=_cmd_serve)

    analyze = subcommands.add_parser("analyze", help="run scan, transcription, sample analysis, or full analysis")
    analyze.add_argument("--config", required=True)
    analyze.add_argument("--stage", required=True, choices=["scan", "transcribe", "sample", "full"])
    analyze.add_argument("--force", action="store_true")
    analyze.set_defaults(func=_cmd_analyze)

    export = subcommands.add_parser("export", help="export CSV, Markdown, HTML, and cut index")
    export.add_argument("--project", required=True)
    export.set_defaults(func=_cmd_export)

    sync = subcommands.add_parser("sync-eagle", help="generate or apply Eagle sync")
    sync.add_argument("--project", required=True)
    mode = sync.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    sync.set_defaults(func=_cmd_sync_eagle)
    return parser


def _cmd_init(args: argparse.Namespace) -> dict[str, Any]:
    payload = {
        "project_name": args.project_name,
        "source_folder": args.source_folder,
        "output_style": args.output_style,
        "target_length": args.target_length,
        "audience": args.audience,
        "people_focus": args.people_focus,
        "audio_priority": args.audio_priority,
        "model_config": {
            "provider": args.model_provider,
            "base_url": args.model_base_url,
            "api_key_env": args.api_key_env,
            "vision_model": args.vision_model,
            "text_model": args.text_model,
            "transcription_model": args.transcription_model,
            "sample_size": args.sample_size,
            "language": "zh-CN",
        },
        "eagle_sync": {"enabled": True, "mode": "dry-run", "base_url": "http://127.0.0.1:41595/api"},
    }
    path = create_project_config(payload)
    return {"config_path": str(path)}


def _cmd_serve(args: argparse.Namespace) -> None:
    try:
        import fastapi  # noqa: F401
        import uvicorn
    except ModuleNotFoundError as exc:
        if exc.name == "fastapi":
            from .local_server import serve_simple

            serve_simple(args.host, args.port)
            return None
        raise RuntimeError("缺少 uvicorn。请先安装项目依赖：pip install -e .") from exc
    uvicorn.run("tripclipper.web:create_app", host=args.host, port=args.port, factory=True)


def _cmd_analyze(args: argparse.Namespace) -> dict[str, Any]:
    data = analyze_project(Path(args.config), args.stage, force=args.force)
    status_block = data.get("transcription") if args.stage == "transcribe" else data.get("analysis")
    return {
        "project": data.get("project", {}).get("project_slug"),
        "stage": args.stage,
        "assets": len(data.get("assets") or []),
        "status": (status_block or {}).get("status"),
        "analysis_status": (data.get("analysis") or {}).get("status"),
        "transcription_status": (data.get("transcription") or {}).get("status"),
        "failures": len(data.get("failures") or []),
        "warnings": len(data.get("warnings") or []),
    }


def _cmd_export(args: argparse.Namespace) -> dict[str, Any]:
    return export_project(args.project)


def _cmd_sync_eagle(args: argparse.Namespace) -> dict[str, Any]:
    if args.apply:
        return eagle_apply(args.project)
    return eagle_dry_run(args.project)


if __name__ == "__main__":
    raise SystemExit(main())
