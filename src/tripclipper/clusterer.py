"""Local heuristic clustering and deterministic default candidate pool generation (M4)."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from .models import (
    AnalysisStatus,
    Asset,
    CutIndex,
    DefaultCandidate,
    EditCandidateStatus,
    SimilarGroup,
    SimilarSelection,
)

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

# Internal heuristic thresholds (private; do not export).
_TIME_WINDOW_SECONDS = 60
_SUBJECT_SIMILARITY_THRESHOLD = 0.6  # primary_subject 2-gram Jaccard
_TAGS_JACCARD_THRESHOLD = 0.5
_SUBJECT_SHOT_BALANCE_TRIGGER_SIZE = 20
_SUBJECT_SHOT_BALANCE_RATIO = 0.5
_SUBJECT_SHOT_BALANCE_MAX_TRIM_RATIO = 0.2
_GROUP_ARBITRATION_LIMIT = 12

# Public mirror for `cluster_runner` to import without piercing the private API.
GROUP_ARBITRATION_LIMIT = _GROUP_ARBITRATION_LIMIT


# ---------------------------------------------------------------------------
# Private dataclass
# ---------------------------------------------------------------------------


@dataclass
class CandidateGroup:
    """A candidate similar-group produced by local heuristic clustering."""

    asset_ids: list[str]
    signal_summary: str  # e.g. "强信号轨" / "语义信号轨"


# ---------------------------------------------------------------------------
# Pure helper functions
# ---------------------------------------------------------------------------


def _text_jaccard_2gram(s1: str, s2: str) -> float:
    """Return the 2-gram Jaccard similarity between two short strings.

    Strings are split into 2-grams character-by-character (works for CJK).
    Returns 0.0 if either side is empty or has length < 2.
    """

    if not isinstance(s1, str) or not isinstance(s2, str):
        return 0.0
    if len(s1) < 2 or len(s2) < 2:
        return 0.0
    grams1 = {s1[i : i + 2] for i in range(len(s1) - 1)}
    grams2 = {s2[i : i + 2] for i in range(len(s2) - 1)}
    if not grams1 or not grams2:
        return 0.0
    intersection = grams1 & grams2
    union = grams1 | grams2
    if not union:
        return 0.0
    return len(intersection) / len(union)


def _tags_jaccard(t1: list[str], t2: list[str]) -> float:
    """Return the set Jaccard similarity between two tag lists. Empty -> 0.0."""

    if not t1 or not t2:
        return 0.0
    set1 = set(t1)
    set2 = set(t2)
    union = set1 | set2
    if not union:
        return 0.0
    return len(set1 & set2) / len(union)


def _modified_time_seconds(asset: Asset) -> Optional[float]:
    """Parse ``asset.modified_time`` (ISO8601) into epoch seconds.

    The field lives at the Asset top level (set by the scan stage), not inside
    ``metadata``. Returns None when missing, not a string, empty, or unparseable.
    """

    raw = asset.modified_time
    if not isinstance(raw, str) or not raw:
        return None
    # ``datetime.fromisoformat`` in 3.11+ handles most ISO8601, but explicitly
    # normalise the trailing 'Z' to '+00:00' for safety on older runtimes.
    normalised = raw.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(normalised)
    except ValueError:
        return None
    try:
        return dt.timestamp()
    except (OverflowError, OSError, ValueError):
        return None


def _similarity_signals(a: Asset, b: Asset) -> tuple[bool, str]:
    """Return ``(is_similar, track_label)`` for two assets.

    Strong signal track (preferred): both ``modified_time`` parse and differ
    by <= 60s, and ``subject_type`` matches.

    Semantic signal track: ``subject_type`` and ``shot_scale`` both match, and
    either primary_subject 2-gram Jaccard >= 0.6 or tags Jaccard >= 0.5.
    """

    # Strong signal first.
    if a.subject_type is not None and a.subject_type == b.subject_type:
        ts_a = _modified_time_seconds(a)
        ts_b = _modified_time_seconds(b)
        if (
            ts_a is not None
            and ts_b is not None
            and abs(ts_a - ts_b) <= _TIME_WINDOW_SECONDS
        ):
            return True, "强信号轨"

    # Semantic signal track.
    if (
        a.subject_type is not None
        and a.subject_type == b.subject_type
        and a.shot_scale is not None
        and a.shot_scale == b.shot_scale
    ):
        subject_sim = _text_jaccard_2gram(a.primary_subject or "", b.primary_subject or "")
        tag_sim = _tags_jaccard(a.tags or [], b.tags or [])
        if (
            subject_sim >= _SUBJECT_SIMILARITY_THRESHOLD
            or tag_sim >= _TAGS_JACCARD_THRESHOLD
        ):
            return True, "语义信号轨"

    return False, ""


# ---------------------------------------------------------------------------
# Union-Find
# ---------------------------------------------------------------------------


class _UnionFind:
    """Standard union-find / disjoint-set data structure (path compression)."""

    def __init__(self) -> None:
        self._parent: dict[str, str] = {}

    def add(self, x: str) -> None:
        if x not in self._parent:
            self._parent[x] = x

    def find(self, x: str) -> str:
        self.add(x)
        # Iterative path compression.
        root = x
        while self._parent[root] != root:
            root = self._parent[root]
        # Compress.
        cur = x
        while self._parent[cur] != root:
            nxt = self._parent[cur]
            self._parent[cur] = root
            cur = nxt
        return root

    def union(self, a: str, b: str) -> None:
        ra = self.find(a)
        rb = self.find(b)
        if ra != rb:
            self._parent[rb] = ra

    def groups(self) -> dict[str, list[str]]:
        result: dict[str, list[str]] = {}
        for x in self._parent:
            root = self.find(x)
            result.setdefault(root, []).append(x)
        return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def cluster_candidates(assets: list[Asset]) -> list[CandidateGroup]:
    """Produce candidate similar-groups (size > 1) from analyzed assets only.

    Filters to ``analysis_status == AnalysisStatus.analyzed``; performs pairwise
    signal checks and union-finds the connected components. Groups of size 1
    are not returned (single-element groups are handled as non-grouped).

    Output ordering is deterministic:
      - Within a group, asset_ids are sorted by ``relative_path or asset_id``.
      - Across groups, groups are sorted by their first asset_id.
    """

    eligible: list[Asset] = [
        a
        for a in assets
        if a.analysis_status == AnalysisStatus.analyzed and a.asset_id
    ]
    if not eligible:
        return []

    # Stable ordering of inputs by (relative_path or asset_id) so pairwise
    # comparison and union order is reproducible.
    eligible_sorted = sorted(
        eligible, key=lambda a: (a.relative_path or a.asset_id or "")
    )
    by_id: dict[str, Asset] = {a.asset_id: a for a in eligible_sorted if a.asset_id}

    uf = _UnionFind()
    for a in eligible_sorted:
        uf.add(a.asset_id)  # type: ignore[arg-type]

    # Track each pair's first hit track so we can summarise per group.
    pair_track: dict[frozenset[str], str] = {}

    n = len(eligible_sorted)
    for i in range(n):
        a = eligible_sorted[i]
        for j in range(i + 1, n):
            b = eligible_sorted[j]
            similar, track = _similarity_signals(a, b)
            if similar:
                pair_track[frozenset({a.asset_id, b.asset_id})] = track
                uf.union(a.asset_id, b.asset_id)  # type: ignore[arg-type]

    raw_groups = uf.groups()

    candidate_groups: list[CandidateGroup] = []
    for _root, members in raw_groups.items():
        if len(members) <= 1:
            continue
        # Sort members deterministically.
        sorted_members = sorted(
            members, key=lambda aid: (by_id[aid].relative_path or aid)
        )
        # Pick a deterministic signal_summary: scan member-pairs in sorted
        # order and take the first hit's track (strong signal naturally wins
        # over semantic when both are present, since both tracks recorded
        # under the same pair are overwritten by the most recent —
        # but pair_track only stored the first ``True`` track per pair).
        signal = ""
        for ii in range(len(sorted_members)):
            for jj in range(ii + 1, len(sorted_members)):
                key = frozenset({sorted_members[ii], sorted_members[jj]})
                hit = pair_track.get(key)
                if hit:
                    signal = hit
                    break
            if signal:
                break
        candidate_groups.append(
            CandidateGroup(asset_ids=sorted_members, signal_summary=signal)
        )

    candidate_groups.sort(key=lambda g: g.asset_ids[0] if g.asset_ids else "")
    return candidate_groups


def apply_similarity_states(cut: CutIndex, groups: list[SimilarGroup]) -> None:
    """Write similar-group membership back into ``cut.assets[*].similar_*``.

    For every member of every ``SimilarGroup`` we set ``similar_group_id``,
    ``similar_selection`` and ``similar_rank`` according to spec Q18:
      - ``primary_asset_id``         -> primary, rank=1
      - ``alternate_asset_ids``      -> alternate, rank=2,3,...
      - ``rejected_asset_ids``       -> rejected, then rank
      - if ``needs_review`` is True, any remaining group member not classified
        above is marked ``needs_review`` ordered by rating desc.

    ``similar_reason`` is intentionally NOT written here — cluster_runner sets
    it according to per-group rules.

    Assets not in any group are reset to a clean state:
      similar_selection=SimilarSelection.none, similar_group_id=None,
      similar_rank=None, similar_reason=None.
    """

    assets_by_id: dict[str, Asset] = {
        a.asset_id: a for a in cut.assets if a.asset_id
    }
    grouped_ids: set[str] = set()

    for group in groups:
        gid = group.similar_group_id
        member_ids = list(group.asset_ids or [])
        rank = 1

        # primary
        if group.primary_asset_id and group.primary_asset_id in assets_by_id:
            asset = assets_by_id[group.primary_asset_id]
            asset.similar_group_id = gid
            asset.similar_selection = SimilarSelection.primary
            asset.similar_rank = rank
            grouped_ids.add(group.primary_asset_id)
            rank += 1

        # alternate (in given order)
        for aid in group.alternate_asset_ids or []:
            if aid in assets_by_id and aid not in grouped_ids:
                asset = assets_by_id[aid]
                asset.similar_group_id = gid
                asset.similar_selection = SimilarSelection.alternate
                asset.similar_rank = rank
                grouped_ids.add(aid)
                rank += 1

        # rejected (in given order)
        for aid in group.rejected_asset_ids or []:
            if aid in assets_by_id and aid not in grouped_ids:
                asset = assets_by_id[aid]
                asset.similar_group_id = gid
                asset.similar_selection = SimilarSelection.rejected
                asset.similar_rank = rank
                grouped_ids.add(aid)
                rank += 1

        # If the whole group needs review, every member not yet classified
        # is tagged needs_review, ordered by rating desc (None last).
        if group.needs_review:
            unclassified = [
                aid
                for aid in member_ids
                if aid in assets_by_id and aid not in grouped_ids
            ]
            unclassified.sort(
                key=lambda aid: (
                    -(assets_by_id[aid].rating if assets_by_id[aid].rating is not None else -1),
                    aid,
                )
            )
            for aid in unclassified:
                asset = assets_by_id[aid]
                asset.similar_group_id = gid
                asset.similar_selection = SimilarSelection.needs_review
                asset.similar_rank = rank
                grouped_ids.add(aid)
                rank += 1

    # Reset assets not in any group.
    for asset in cut.assets:
        if not asset.asset_id or asset.asset_id in grouped_ids:
            continue
        asset.similar_group_id = None
        asset.similar_selection = SimilarSelection.none
        asset.similar_rank = None
        asset.similar_reason = None


def build_default_candidates(cut: CutIndex) -> list[DefaultCandidate]:
    """Generate the default edit candidate pool by deterministic post-processing.

    See spec Q6 for the full state-machine. Writes back
    ``edit_candidate_status`` / ``edit_candidate_reason`` /
    ``edit_candidate_priority`` on every relevant asset, populates
    ``cut.default_candidates`` and returns the same list (default_selected
    only, sorted by priority).
    """

    # Step 1: classify every asset.
    initial_default_ids: set[str] = set()

    for asset in cut.assets:
        if not asset.asset_id:
            continue

        # Non-analyzed assets: needs_review (analysis incomplete).
        if asset.analysis_status != AnalysisStatus.analyzed:
            asset.edit_candidate_status = EditCandidateStatus.needs_review
            asset.edit_candidate_reason = "分析未完成，待人工确认"
            asset.edit_candidate_priority = None
            continue

        selection = asset.similar_selection

        # needs_review group member.
        if selection == SimilarSelection.needs_review:
            asset.edit_candidate_status = EditCandidateStatus.needs_review
            asset.edit_candidate_reason = "所在雷同组置信度不足，待人工确认"
            asset.edit_candidate_priority = None
            continue

        # alternate within a group -> pool alternate.
        if selection == SimilarSelection.alternate:
            gid = asset.similar_group_id or ""
            asset.edit_candidate_status = EditCandidateStatus.alternate
            asset.edit_candidate_reason = f"组『{gid}』备选"
            asset.edit_candidate_priority = None
            continue

        # rejected within a group -> excluded from pool.
        if selection == SimilarSelection.rejected:
            gid = asset.similar_group_id or ""
            asset.edit_candidate_status = EditCandidateStatus.excluded
            asset.edit_candidate_reason = f"组『{gid}』被仲裁判定不推荐"
            asset.edit_candidate_priority = None
            continue

        # Initial default-selected set: primary OR ungrouped (none / None).
        if selection == SimilarSelection.primary:
            gid = asset.similar_group_id or ""
            asset.edit_candidate_status = EditCandidateStatus.default_selected
            asset.edit_candidate_reason = f"组『{gid}』主选，默认入选"
            asset.edit_candidate_priority = None
            initial_default_ids.add(asset.asset_id)
        elif selection is None or selection == SimilarSelection.none:
            asset.edit_candidate_status = EditCandidateStatus.default_selected
            asset.edit_candidate_reason = "非雷同高星素材，默认入选"
            asset.edit_candidate_priority = None
            initial_default_ids.add(asset.asset_id)
        else:
            # Defensive fallback for any unanticipated enum value: treat as
            # needs_review to avoid silently dropping an asset.
            asset.edit_candidate_status = EditCandidateStatus.needs_review
            asset.edit_candidate_reason = "状态未知，待人工确认"
            asset.edit_candidate_priority = None

    # Step 2: subject x shot_scale balance trim.
    initial_default_count = len(initial_default_ids)
    if initial_default_count >= _SUBJECT_SHOT_BALANCE_TRIGGER_SIZE:
        max_trim = math.floor(
            initial_default_count * _SUBJECT_SHOT_BALANCE_MAX_TRIM_RATIO
        )
        trimmed = 0
        # Loop until no bucket exceeds the cap or trim cap reached.
        while trimmed < max_trim:
            current_default_assets = [
                a
                for a in cut.assets
                if a.asset_id
                and a.edit_candidate_status == EditCandidateStatus.default_selected
            ]
            current_size = len(current_default_assets)
            if current_size == 0:
                break

            # Bucket counts by (subject_type, shot_scale).
            buckets: dict[tuple, list[Asset]] = {}
            for a in current_default_assets:
                key = (a.subject_type, a.shot_scale)
                buckets.setdefault(key, []).append(a)

            # Find the most over-represented bucket whose share > 50%.
            over_key = None
            over_assets: list[Asset] = []
            for key, members in buckets.items():
                share = len(members) / current_size
                if share > _SUBJECT_SHOT_BALANCE_RATIO:
                    if over_key is None or len(members) > len(over_assets):
                        over_key = key
                        over_assets = members
            if over_key is None:
                break

            # Demote the lowest-rated asset in that bucket to alternate.
            over_assets.sort(
                key=lambda a: (
                    a.rating if a.rating is not None else -1,
                    a.asset_id or "",
                )
            )
            victim = over_assets[0]
            victim.edit_candidate_status = EditCandidateStatus.alternate
            victim.edit_candidate_reason = "为景别平衡入选 alternate"
            victim.edit_candidate_priority = None
            trimmed += 1

    # Step 3: assign edit_candidate_priority over (status, -rating, asset_id).
    status_rank = {
        EditCandidateStatus.default_selected: 0,
        EditCandidateStatus.alternate: 1,
    }

    def _priority_key(a: Asset) -> tuple:
        rating = a.rating if a.rating is not None else 0
        sr = status_rank.get(a.edit_candidate_status, 99)
        return (sr, -rating, a.asset_id or "")

    rankable = [
        a
        for a in cut.assets
        if a.asset_id
        and a.edit_candidate_status
        in (EditCandidateStatus.default_selected, EditCandidateStatus.alternate)
    ]
    rankable.sort(key=_priority_key)
    for idx, asset in enumerate(rankable, start=1):
        asset.edit_candidate_priority = idx

    # Step 4: build DefaultCandidate list (default_selected only, by priority).
    default_assets = [
        a
        for a in cut.assets
        if a.asset_id
        and a.edit_candidate_status == EditCandidateStatus.default_selected
    ]
    default_assets.sort(
        key=lambda a: (
            a.edit_candidate_priority
            if a.edit_candidate_priority is not None
            else 10**9,
            a.asset_id or "",
        )
    )
    candidates: list[DefaultCandidate] = [
        DefaultCandidate(
            asset_id=a.asset_id,
            priority=a.edit_candidate_priority,
            reason=a.edit_candidate_reason,
            similar_group_id=a.similar_group_id,
            subject_type=a.subject_type,
            shot_scale=a.shot_scale,
        )
        for a in default_assets
    ]

    cut.default_candidates = candidates
    return candidates


__all__ = [
    "CandidateGroup",
    "GROUP_ARBITRATION_LIMIT",
    "cluster_candidates",
    "apply_similarity_states",
    "build_default_candidates",
]
