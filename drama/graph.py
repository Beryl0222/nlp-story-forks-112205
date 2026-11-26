"""分支图遍历。

- 每条路线在每个变体候选组只选一条台词，保证“一个片段只登记一份剧情事实”。
- 允许回头路；回到同一房间不清历史，但当判断相关状态与此前完全相同时剪枝，
  不再为每次点返回生成全新待审路线。
- trace 支持编剧给一条实际选择顺序，逐步看到承诺依据在哪里断掉。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Sequence

from .acts import Classification, classify_all
from .model import Edge, Line, Script
from .state import (
    RouteState,
    TriggerResult,
    enter_scene,
    evaluate_trigger,
    initial_state,
)

# 图中存在回头环，设一个远大于合理剧情节数的硬上限兜底
MAX_STEPS = 32


@dataclass(frozen=True)
class Route:
    route_id: str
    edges: tuple[str, ...]
    scenes: tuple[str, ...]
    end_scene: str
    state: RouteState
    variant_choices: Mapping[tuple, str]
    trigger_results: tuple[TriggerResult, ...]
    terminal: bool
    pruned: bool = False
    prune_reason: str = ""

    @property
    def choice_sequence(self) -> tuple[str, ...]:
        return self.edges


@dataclass(frozen=True)
class TraceStep:
    index: int
    edge: Edge | None
    trigger: TriggerResult | None
    scene: str
    lines_played: tuple[str, ...]
    state: RouteState


@dataclass(frozen=True)
class TraceReport:
    entry: str
    steps: tuple[TraceStep, ...]
    reached: str
    blocked_edge: str | None
    reason: str


@dataclass
class WalkResult:
    routes: list[Route] = field(default_factory=list)
    # 被剪枝的重复循环，只保留一条说明而不是每条都变待审路线
    pruned: list[dict[str, str]] = field(default_factory=list)
    # 触发条件不成立的边：阻断与待确认问题登记在来源场景的路线末端
    dead_edges: list[dict[str, object]] = field(default_factory=list)
    classifications: Mapping[str, Classification] = field(default_factory=dict)


def _variant_options(
    script: Script, scene_id: str, visit_number: int
) -> list[dict[tuple, str]]:
    """该场景第 visit_number 次到访时每个候选组的全部可选台词。

    返回三元键 (scene,line_no,visit)，只作用于这一次到访，不污染其他次访问。
    """

    groups = [
        group
        for key, group in sorted(script.variant_groups().items())
        if key[0] == scene_id and len(group) > 1
    ]
    if not groups:
        return [{}]
    choices: list[dict[tuple, str]] = [{}]
    for group in groups:
        key = (*group[0].key, visit_number)
        expanded: list[dict[tuple, str]] = []
        for partial in choices:
            for line in group:
                expanded.append({**partial, key: line.id})
        choices = expanded
    return choices


def walk(script: Script, entry: str | None = None) -> WalkResult:
    entry = entry or (script.releases[0].entry if script.releases else script.scenes[0].id)
    classifications = classify_all(script)
    result = WalkResult(classifications=classifications)
    counter = {"route": 0, "prune": 0}

    def expand(
        state: RouteState,
        edges: tuple[str, ...],
        triggers: tuple[TriggerResult, ...],
        local_seen: frozenset[tuple[str, str]],
    ) -> None:
        if len(edges) >= MAX_STEPS:
            counter["route"] += 1
            result.routes.append(
                Route(
                    f"R{counter['route']:03d}",
                    edges,
                    state.visits,
                    state.scene or entry,
                    state,
                    dict(state.chosen_variants),
                    triggers,
                    terminal=True,
                    pruned=True,
                    prune_reason=f"达到 {MAX_STEPS} 步硬上限",
                )
            )
            return

        outgoing = script.edges_from(state.scene or "")
        if not outgoing:
            counter["route"] += 1
            result.routes.append(
                Route(
                    f"R{counter['route']:03d}",
                    edges,
                    state.visits,
                    state.scene or entry,
                    state,
                    dict(state.chosen_variants),
                    triggers,
                    terminal=True,
                )
            )
            return

        for edge in outgoing:
            # 先进入目标场景并应用该幕台词，再判定 trigger：
            # 例如 E1 的“余舟答应留下”由 S2 的 L2 建立，必须在 S2 状态上回答
            visit_number = state.visit_count.get(edge.target, 0) + 1
            for variant_choice in _variant_options(
                script, edge.target, visit_number
            ):
                candidate = enter_scene(state, edge.target, classifications, variant_choice)
                trigger = evaluate_trigger(candidate, edge, classifications)
                if not trigger.satisfied:
                    # 没有依据的边不能把角色带进下一幕，登记死边供审查输出
                    result.dead_edges.append(
                        {
                            "route_edges": edges,
                            "origin_scene": state.scene,
                            "scene": edge.target,
                            "edge": edge,
                            "trigger": trigger,
                        }
                    )
                    continue
                signature_key = (edge.target, candidate.judgement_signature())
                if signature_key in local_seen:
                    # 仅剪“沿本路线回到判断等价状态”的环；不同来路互不影响
                    counter["prune"] += 1
                    result.pruned.append(
                        {
                            "prune_id": f"P{counter['prune']:03d}",
                            "scene": edge.target,
                            "signature": signature_key[1],
                            "via_edge": edge.id,
                            "choice_prefix": list(edges),
                            "reason": "沿本路线回到判断相关状态完全相同的场景，循环差异不再改变后续判断",
                        }
                    )
                    continue
                expand(
                    candidate,
                    (*edges, edge.id),
                    (*triggers, trigger),
                    local_seen | {signature_key},
                )

    root = initial_state(script, entry)
    # 入口场景自身的台词先应用（S1 的 L1）
    root = enter_scene(root, entry, classifications)
    root_seen = frozenset({(entry, root.judgement_signature())})
    expand(root, (), (), root_seen)
    return result


def trace(
    script: Script,
    edge_sequence: Sequence[str],
    entry: str | None = None,
    variant_choices: Mapping[tuple, str] | None = None,
) -> TraceReport:
    """按观众实际选择顺序走一遍，逐步返回状态，定位依据断点。"""

    entry = entry or (script.releases[0].entry if script.releases else script.scenes[0].id)
    classifications = classify_all(script)
    state = enter_scene(initial_state(script, entry), entry, classifications, variant_choices)
    steps: list[TraceStep] = [
        TraceStep(0, None, None, entry, tuple(state.line_events), state)
    ]
    blocked: str | None = None
    reason = ""

    for index, edge_id in enumerate(edge_sequence, start=1):
        if blocked is not None:
            break
        edge = script.edge(edge_id)
        if edge.origin != state.scene:
            blocked = edge_id
            reason = f"边 {edge_id} 的起点 {edge.origin} 与当前场景 {state.scene} 不符"
            break
        # 先进入目标场景应用该幕台词，再回答该边 trigger 是否成立
        before = set(state.line_events)
        candidate = enter_scene(state, edge.target, classifications, variant_choices)
        trigger = evaluate_trigger(candidate, edge, classifications)
        if not trigger.satisfied:
            blocked = edge_id
            reason = trigger.question or (
                f"触发条件“{edge.trigger}”在当前路线状态下不成立，且无可用依据"
            )
            steps.append(
                TraceStep(index, edge, trigger, edge.target, (), candidate)
            )
            break
        state = candidate
        played = tuple(line_id for line_id in state.line_events if line_id not in before)
        steps.append(TraceStep(index, edge, trigger, edge.target, played, state))

    return TraceReport(entry, tuple(steps), state.scene or entry, blocked, reason)


def played_lines(route: Route) -> tuple[Line, ...]:
    return tuple(route.state.script.line(line_id) for line_id in route.state.line_events)
