from __future__ import annotations

from pathlib import Path

from experiments.clip_selection.contracts import SelectionRun


class PolicyGuardedSelectionStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def save_checkpoint(self, run: SelectionRun) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        run.checkpoint_count += 1
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(run.model_dump_json(indent=2), encoding="utf-8")
        temporary.replace(self.path)

    def load(self) -> SelectionRun:
        return SelectionRun.model_validate_json(self.path.read_text(encoding="utf-8"))

