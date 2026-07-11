"""Export rough-cut plans to Jianying draft content."""

from __future__ import annotations

from pathlib import Path
from typing import Mapping

from tripclipper.cut_index import read_cut_index
from tripclipper.models import Asset, CutIndex
from tripclipper.roughcut import RoughCutPlan, RoughCutSegment

from .adapters.base import JianyingDraftAdapter
from .models import DraftExportError, DraftExportResult


class JianyingDraftExporter:
    """Thin engine dispatcher and boundary guard for Jianying draft export."""

    DEFAULT_ENGINE = "pyjianyingdraft"

    def __init__(self, adapters: Mapping[str, JianyingDraftAdapter | None] | None = None) -> None:
        self._adapters: dict[str, JianyingDraftAdapter | None] = (
            {self.DEFAULT_ENGINE: None} if adapters is None else dict(adapters)
        )

    def export(
        self,
        plan: RoughCutPlan,
        output_dir: Path | str,
        *,
        engine: str = DEFAULT_ENGINE,
    ) -> DraftExportResult:
        adapter = self._adapter_for(engine)
        media_paths = self._resolve_media_paths(plan)
        target_dir = Path(output_dir).expanduser()
        if target_dir.exists() and not target_dir.is_dir():
            raise DraftExportError(f"output_dir must be a directory: {target_dir}")
        target_dir.mkdir(parents=True, exist_ok=True)

        result = adapter.export(
            plan=plan,
            media_paths=media_paths,
            output_dir=target_dir,
            engine=engine,
        )
        self._validate_result(result, target_dir)
        return result

    def _adapter_for(self, engine: str) -> JianyingDraftAdapter:
        if engine not in self._adapters:
            supported = ", ".join(sorted(self._adapters)) or "(none)"
            raise DraftExportError(f"Unsupported export engine {engine!r}; supported engines: {supported}")
        adapter = self._adapters[engine]
        if adapter is None:
            from .adapters.pyjianyingdraft import PyJianYingDraftAdapter

            adapter = PyJianYingDraftAdapter()
            self._adapters[engine] = adapter
        return adapter

    def _resolve_media_paths(self, plan: RoughCutPlan) -> dict[str, Path]:
        cut_index = self._load_cut_index(plan.project.cut_index_path)
        assets_by_id = {
            asset.asset_id: asset
            for asset in (cut_index.assets if cut_index is not None else [])
            if asset.asset_id is not None
        }
        media_paths: dict[str, Path] = {}

        for segment in plan.timeline:
            if segment.track_type == "text":
                continue
            media_paths[segment.segment_id] = self._resolve_segment_media(
                segment,
                cut_index,
                assets_by_id,
            )
        return media_paths

    def _load_cut_index(self, path_value: str) -> CutIndex | None:
        path = self._resolve_existing_path(path_value, [Path.cwd()])
        if path is None:
            return None
        try:
            return read_cut_index(path)
        except Exception as exc:
            raise DraftExportError(f"Unable to read cut index {path}: {exc}") from exc

    def _resolve_segment_media(
        self,
        segment: RoughCutSegment,
        cut_index: CutIndex | None,
        assets_by_id: Mapping[str, Asset],
    ) -> Path:
        candidates: list[str] = []
        if cut_index is not None:
            asset = assets_by_id.get(segment.asset_id)
            if asset is None:
                raise DraftExportError(
                    f"{segment.segment_id}: asset_id {segment.asset_id!r} not found in cut index"
                )
            self._validate_asset_identity(segment, asset)
            candidates.extend(self._cut_index_path_candidates(cut_index, asset, segment))

        if segment.asset_path:
            candidates.append(segment.asset_path)

        resolved = self._first_readable_path(candidates)
        if resolved is None:
            joined = ", ".join(candidates) or "(no media path candidates)"
            raise DraftExportError(
                f"{segment.segment_id}: unable to resolve readable media path from {joined}"
            )
        return resolved

    @staticmethod
    def _validate_asset_identity(segment: RoughCutSegment, asset: Asset) -> None:
        if (
            asset.relative_path
            and segment.asset_relative_path
            and asset.relative_path != segment.asset_relative_path
        ):
            raise DraftExportError(
                f"{segment.segment_id}: asset_relative_path {segment.asset_relative_path!r} "
                f"does not match cut index relative path {asset.relative_path!r}"
            )
        if asset.type is not None and segment.asset_type is not None and asset.type != segment.asset_type:
            raise DraftExportError(
                f"{segment.segment_id}: asset_type {segment.asset_type!r} does not match cut index"
            )

    def _cut_index_path_candidates(
        self,
        cut_index: CutIndex,
        asset: Asset,
        segment: RoughCutSegment,
    ) -> list[str]:
        candidates: list[str] = []
        if asset.path:
            candidates.append(asset.path)

        source_folder = cut_index.project.source_folder
        for relative_path in (asset.relative_path, segment.asset_relative_path):
            if source_folder and relative_path:
                candidates.append(str(Path(source_folder) / relative_path))
            elif relative_path:
                candidates.append(relative_path)
        return candidates

    def _first_readable_path(self, candidates: list[str]) -> Path | None:
        for candidate in candidates:
            resolved = self._resolve_existing_path(candidate, [Path.cwd()])
            if resolved is not None:
                return resolved
        return None

    @staticmethod
    def _resolve_existing_path(path_value: str, roots: list[Path]) -> Path | None:
        raw = Path(path_value).expanduser()
        if raw.is_absolute():
            return raw if raw.is_file() else None

        for root in roots:
            candidate = root / raw
            if candidate.is_file():
                return candidate
        return None

    @staticmethod
    def _validate_result(result: DraftExportResult, output_dir: Path) -> None:
        if not result.draft_content_path.is_file():
            raise DraftExportError(
                f"Adapter did not write draft_content.json: {result.draft_content_path}"
            )

        paths = [result.draft_content_path]
        if result.draft_meta_info_path is not None:
            paths.append(result.draft_meta_info_path)

        output_root = output_dir.resolve()
        for path in paths:
            try:
                path.resolve().relative_to(output_root)
            except ValueError as exc:
                raise DraftExportError(
                    f"Adapter wrote export artifact outside output_dir: {path}"
                ) from exc
