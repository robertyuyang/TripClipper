"""Base interface for Jianying draft export adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Mapping

from tripclipper.roughcut import RoughCutPlan

from ..models import AdapterCapabilities, DraftExportResult


class JianyingDraftAdapter(ABC):
    """Adapter interface for converting a selected timeline into draft content."""

    capabilities = AdapterCapabilities()

    @abstractmethod
    def export(
        self,
        *,
        plan: RoughCutPlan,
        media_paths: Mapping[str, Path],
        output_dir: Path,
        engine: str,
    ) -> DraftExportResult:
        """Write draft export artifacts for ``plan`` under ``output_dir``."""
