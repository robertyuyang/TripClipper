from __future__ import annotations

from experiments.clip_selection.contracts import (
    AgentAction,
    CandidateClip,
    ContentCategory,
    FrameSource,
    ProjectSnapshot,
    SelectionRun,
)

from .policy import SelectionPolicy


def apply_action(
    run: SelectionRun,
    action: AgentAction,
    snapshot: ProjectSnapshot,
    frame_source: FrameSource,
    policy: SelectionPolicy,
) -> tuple[bool, list[str]]:
    if action.name == "list_assets":
        run.observations.append(f"索引包含 {len(snapshot.assets)} 个素材")
        return False, []
    if action.name == "inspect_range":
        asset_id = str(action.arguments["asset_id"])
        start = float(action.arguments["start_sec"])
        end = float(action.arguments["end_sec"])
        asset = snapshot.asset(asset_id)
        if start < 0 or end <= start or (asset.duration_sec is not None and end > asset.duration_sec):
            return False, ["inspect_range 时间范围非法"]
        observation = frame_source.inspect(asset_id, start, end)
        run.frame_requests += 1
        run.latest_frame_paths = list(observation.frame_paths)
        run.observations.append(observation.description)
        return False, []
    if action.name == "upsert_candidate":
        clip = CandidateClip.model_validate(action.arguments)
        errors = policy.validate_candidate(run, clip, snapshot)
        if errors:
            return False, errors
        run.clips = [item for item in run.clips if item.clip_id != clip.clip_id]
        run.clips.append(clip)
        return False, []
    if action.name == "set_categories":
        run.categories = [
            ContentCategory.model_validate(item)
            for item in action.arguments.get("categories", [])
        ]
        return False, []
    if action.name == "request_finish":
        return True, policy.validate_finish(run)
    raise ValueError(f"未知 Tool: {action.name}")
