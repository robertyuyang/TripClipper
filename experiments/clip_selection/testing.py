"""离线测试替身。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .contracts import AgentAction, AgentDecision, FrameObservation


class ScriptedAgent:
    def __init__(self, decisions: list[AgentDecision]) -> None:
        self._decisions = list(decisions)
        self.contexts: list[dict[str, Any]] = []

    def decide(self, context: dict[str, Any]) -> AgentDecision:
        self.contexts.append(context)
        if self._decisions:
            return self._decisions.pop(0)
        return AgentDecision(
            action=AgentAction(name="request_finish", arguments={}),
            rationale="脚本动作已耗尽",
        )


class FakeModelClient:
    def __init__(self, decisions: list[AgentDecision]) -> None:
        self.agent = ScriptedAgent(decisions)

    def decide(
        self,
        system_prompt: str,
        context: dict[str, Any],
        images: list[Path] | None = None,
    ) -> AgentDecision:
        return self.agent.decide(context)


class FakeFrameSource:
    def __init__(self) -> None:
        self.calls: list[tuple[str, float, float]] = []

    def inspect(self, asset_id: str, start_sec: float, end_sec: float) -> FrameObservation:
        self.calls.append((asset_id, start_sec, end_sec))
        return FrameObservation(
            asset_id=asset_id,
            start_sec=start_sec,
            end_sec=end_sec,
            description=f"已查看 {asset_id} 的 {start_sec:g}-{end_sec:g} 秒",
        )

