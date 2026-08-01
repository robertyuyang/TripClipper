from experiments.clip_selection.contracts import CandidateClip, ClipStatus, SelectionRun


class SelectionPolicy:
    def validate_candidate(self, run: SelectionRun, clip: CandidateClip) -> list[str]:
        errors: list[str] = []
        if clip.status is ClipStatus.primary and not clip.evidence.strip():
            errors.append("primary 缺少 evidence")
        if clip.status is ClipStatus.primary and not clip.project_role.strip():
            errors.append("primary 缺少 project_role")
        if clip.status is ClipStatus.needs_review and not (clip.review_reason or "").strip():
            errors.append("needs_review 缺少 review_reason")
        review_count = sum(item.status is ClipStatus.needs_review for item in run.clips)
        if clip.status is ClipStatus.needs_review and review_count >= run.brief.max_review_clips:
            errors.append("needs_review 超过 max_review_clips")
        return errors

