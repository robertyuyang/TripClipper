from __future__ import annotations

from pathlib import Path

from experiments.clip_selection.contracts import (
    FrameSource,
    ModelClient,
    ProjectSnapshot,
    RunStatus,
    SelectionRequest,
    SelectionRun,
)
from experiments.clip_selection.runtime import finish_errors, model_context, structure_fingerprint

from .agent import SYSTEM_PROMPT
from .store import AgentOwnedSelectionStore
from .tools import apply_action


class AgentOwnedSelectionHarness:
    def __init__(self, *, model_client: ModelClient, frame_source: FrameSource) -> None:
        self.model_client = model_client
        self.frame_source = frame_source

    def run(self, request: SelectionRequest) -> SelectionRun:
        snapshot = ProjectSnapshot.from_cut_index(request.cut_index_path)
        if snapshot.project_slug != request.project_slug:
            raise ValueError("project_slug 与 cut_index 不匹配")
        run = SelectionRun(
            selection_id=request.selection_id,
            project_slug=request.project_slug,
            brief=request.brief,
            source_cut_index=str(request.cut_index_path),
            source_cut_index_sha256=snapshot.sha256,
        )
        return self._execute(request, snapshot, run)

    def resume(self, request: SelectionRequest) -> SelectionRun:
        snapshot = ProjectSnapshot.from_cut_index(request.cut_index_path)
        store = AgentOwnedSelectionStore(request.output_path)
        run = store.load()
        if run.source_cut_index_sha256 != snapshot.sha256:
            raise ValueError("cut_index 已变化，不能恢复")
        return self._execute(request, snapshot, run)

    def _execute(
        self,
        request: SelectionRequest,
        snapshot: ProjectSnapshot,
        run: SelectionRun,
    ) -> SelectionRun:
        store = AgentOwnedSelectionStore(request.output_path)
        while run.rounds < request.budget.max_rounds:
            images = [Path(path) for path in run.latest_frame_paths if Path(path).is_file()]
            decision = self.model_client.decide(
                SYSTEM_PROMPT,
                model_context(run, snapshot),
                images,
            )
            run.latest_frame_paths = []
            run.rounds += 1
            run.action_trace.append(decision.action.name)
            if (
                decision.action.name == "inspect_range"
                and run.frame_requests >= request.budget.max_frame_requests
            ):
                run.run_status = RunStatus.incomplete
                run.unresolved.append("帧查看预算已耗尽")
                store.save_checkpoint(run)
                return run
            try:
                should_finish = apply_action(run, decision.action, snapshot, self.frame_source)
            except (KeyError, TypeError, ValueError) as exc:
                run.rejected_actions += 1
                run.observations.append(str(exc))
                store.save_checkpoint(run)
                continue
            if should_finish:
                errors = finish_errors(run)
                if errors:
                    run.rejected_actions += 1
                    run.observations.extend(errors)
                    store.save_checkpoint(run)
                    continue
                fingerprint = structure_fingerprint(run)
                if run.last_finish_fingerprint != fingerprint:
                    run.last_finish_fingerprint = fingerprint
                    run.observations.append("需要再完成一轮无结构变化的稳定审计")
                    store.save_checkpoint(run)
                    continue
                run.run_status = RunStatus.completed
                store.save_checkpoint(run)
                return run
            store.save_checkpoint(run)
        run.run_status = RunStatus.incomplete
        run.unresolved.append("达到最大轮数")
        store.save_checkpoint(run)
        return run
