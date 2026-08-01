from experiments.clip_selection.contracts import CandidateClip, ClipStatus, ProjectSnapshot, SelectionRun
from experiments.clip_selection.runtime import finish_errors, validate_clip_reference


class SelectionPolicy:
    def validate_candidate(
        self,
        run: SelectionRun,
        clip: CandidateClip,
        snapshot: ProjectSnapshot,
    ) -> list[str]:
        errors: list[str] = []
        try:
            validate_clip_reference(clip, snapshot)
        except ValueError as exc:
            errors.append(str(exc))
        if clip.status is ClipStatus.primary and not clip.evidence.strip():
            errors.append("primary 缺少 evidence")
        if clip.status is ClipStatus.primary and not clip.project_role.strip():
            errors.append("primary 缺少 project_role")
        if clip.status is ClipStatus.needs_review and not (clip.review_reason or "").strip():
            errors.append("needs_review 缺少 review_reason")
        other_reviews = sum(
            item.status is ClipStatus.needs_review and item.clip_id != clip.clip_id
            for item in run.clips
        )
        if clip.status is ClipStatus.needs_review and other_reviews >= run.brief.max_review_clips:
            errors.append("needs_review 超过 max_review_clips")
        if clip.alternate_for and clip.alternate_for == clip.clip_id:
            errors.append("alternate_for 不能引用自身")
        existing_ids = {item.clip_id for item in run.clips}
        if clip.alternate_for and clip.alternate_for not in existing_ids:
            errors.append("alternate_for 引用不存在的片段")
        known_categories = {item.category_id for item in run.categories}
        unknown_categories = sorted(set(clip.categories) - known_categories)
        if unknown_categories:
            errors.append(f"引用未知分类: {', '.join(unknown_categories)}")
        return errors

    def validate_finish(self, run: SelectionRun) -> list[str]:
        return finish_errors(run)
