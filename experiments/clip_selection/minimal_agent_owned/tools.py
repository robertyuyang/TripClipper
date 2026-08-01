from __future__ import annotations

from experiments.clip_selection.contracts import AgentAction, CandidateClip, SelectionRun


def apply_action(run: SelectionRun, action: AgentAction) -> bool:
    if action.name == "upsert_candidate":
        clip = CandidateClip.model_validate(action.arguments)
        run.clips = [item for item in run.clips if item.clip_id != clip.clip_id]
        run.clips.append(clip)
        return False
    if action.name == "request_finish":
        return True
    if action.name in {"list_assets", "inspect_range", "set_categories"}:
        run.observations.append(f"已执行 {action.name}")
        return False
    raise ValueError(f"未知 Tool: {action.name}")

