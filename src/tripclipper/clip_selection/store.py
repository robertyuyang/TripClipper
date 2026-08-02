"""选片状态与追加式事件的持久化。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import SelectionState


class SelectionStore:
    def __init__(self, task_dir: Path) -> None:
        self.task_dir = task_dir
        self.state_path = task_dir / "state.json"
        self.events_path = task_dir / "events.jsonl"

    def save(self, state: SelectionState) -> None:
        """先完整写临时文件，再在同一文件系统内原子替换。"""
        self.task_dir.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_name(f"{self.state_path.name}.tmp")
        payload = state.model_dump(mode="json")
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        temporary.replace(self.state_path)

    def append_event(
        self,
        event_type: str,
        *,
        tool: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> None:
        self.task_dir.mkdir(parents=True, exist_ok=True)
        event = {
            "occurred_at": datetime.now(timezone.utc).isoformat(),
            "event_type": event_type,
            "tool": tool,
            "data": data or {},
        }
        with self.events_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")


__all__ = ["SelectionStore"]
