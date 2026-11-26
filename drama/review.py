"""剧本依据审查。

两层输出：

1. 路线内 findings：某条具体选择顺序上，哪一幕的动作或台词失去依据。
2. 共用场景兼容性：同一句候选台词在所有准备开放的来路上是否都说得通；
   说不通时指出是哪一组选择（route + 边序列）让它断了。

确认单（confirmations）只能解决“两种读法”的读法问题，不能补出交付事实；
且确认键含上下文签名，只在台词与分支上下文真正相同的出现位置生效。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from .acts import Act, Classification
from .graph import Route, WalkResult, walk
from .model import Edge, Line, Script
from .state import (
    HOLDER_YUZHOU,
    KEY_ITEM,
    RouteState,
    TriggerResult,
)

SEVERITY_BLOCK = "block"        # 必须处理才能交片
SEVERITY_QUESTION = "question"  # 等编剧确认读法
SEVERITY_NOTE = "note"          # 可追溯提示，不阻断


@dataclass(frozen=True)
class Finding:
    code: str
    severity: str
    route_id: str
    scene: str
    line_id: str | None
    edge_id: str | None
    message: str
    evidence: tuple[str, ...]
    confirm_key: str | None = None
    # 让台词/动作断掉的那组选择
    choice_sequence: tuple[str, ...] = ()


@dataclass(frozen=True)
class Compatibility:
    scene: str
    line_id: str
    quote: str
    viable_routes: tuple[str, ...]
    broken_routes: tuple[tuple[str, tuple[str, ...]], ...]  # (route_id, 边序列)
    works_everywhere: bool


@dataclass(frozen=True)
class ReviewReport:
    findings: tuple[Finding, ...]
    questions: tuple[Finding, ...]
    compatibilities: tuple[Compatibility, ...]
    pruned_loops: tuple[dict[str, str], ...]
    routes: tuple[Route, ...]
    classifications: Mapping[str, Classification]


def _trigger_findings(route: Route) -> list[Finding]:
    findings: list[Finding] = []
    for result in route.trigger_results:
        if result.satisfied:
            continue
        if result.question_key:
            findings.append(
                Finding(
                    "TRIGGER-AMBIGUOUS",
                    SEVERITY_QUESTION,
                    route.route_id,
                    route.state.scene or "",
                    None,
                    result.edge.id,
                    result.question or "触发条件存在两种读法",
                    result.evidence,
                    confirm_key=result.question_key,
                    choice_sequence=route.edges,
                )
            )
        else:
            findings.append(
                Finding(
                    "TRIGGER-UNGROUNDED",
                    SEVERITY_BLOCK,
                    route.route_id,
                    route.state.scene or "",
                    None,
                    result.edge.id,
                    f"边 {result.edge.id} 的触发条件“{result.edge.trigger}”没有成立依据",
                    result.evidence,
                    choice_sequence=route.edges,
                )
            )
    return findings


def _dead_edge_findings(
    script: Script, walk_result: WalkResult
) -> list[Finding]:
    """遍历期被拦下的边：给出让台词或动作断掉的那组选择。"""

    findings: list[Finding] = []
    for index, dead in enumerate(walk_result.dead_edges, start=1):
        edge: Edge = dead["edge"]  # type: ignore[assignment]
        trigger: TriggerResult = dead["trigger"]  # type: ignore[assignment]
        route_edges: tuple[str, ...] = tuple(dead["route_edges"])  # type: ignore[arg-type]
        scene: str = dead["origin_scene"]  # type: ignore[assignment]
        route_id = f"D{index:03d}"
        if trigger.question_key:
            findings.append(
                Finding(
                    "TRIGGER-AMBIGUOUS",
                    SEVERITY_QUESTION,
                    route_id,
                    scene,
                    None,
                    edge.id,
                    trigger.question or "触发条件存在两种读法",
                    trigger.evidence,
                    confirm_key=trigger.question_key,
                    choice_sequence=(*route_edges, edge.id),
                )
            )
        else:
            findings.append(
                Finding(
                    "TRIGGER-UNGROUNDED",
                    SEVERITY_BLOCK,
                    route_id,
                    scene,
                    None,
                    edge.id,
                    f"边 {edge.id} 的触发条件“{edge.trigger}”没有成立依据，选项后没有可播放的成立段落",
                    trigger.evidence,
                    choice_sequence=(*route_edges, edge.id),
                )
            )
    return findings


def _line_findings(
    script: Script,
    route: Route,
    classifications: Mapping[str, Classification],
) -> list[Finding]:
    findings: list[Finding] = []
    state = route.state

    for line_id in state.line_events:
        line = script.line(line_id)
        classification = classifications[line_id]
        act = classification.act

        if act is Act.ACTION_CLAIM:
            # L6：主张用“刚交给我”的钥匙，必须有仍然有效的直接交付依据，且人在钥匙间
            handover = state.latest_valid(f"handover:{KEY_ITEM}")
            if handover is None or state.key_holder != HOLDER_YUZHOU:
                basis_lines = tuple(
                    fact.source_line
                    for fact in state.facts
                    if fact.fact_key in (
                        f"report:handover:{KEY_ITEM}",
                        "retraction:handover_belief",
                        "promise:conditional_key_custody",
                    )
                )
                findings.append(
                    Finding(
                        "ACTION-NO-KEY",
                        SEVERITY_BLOCK,
                        route.route_id,
                        line.scene,
                        line.id,
                        None,
                        "角色要用一把这条路线上从未实际拿到的钥匙：只有许诺/转述/改口，没有直接交付依据",
                        basis_lines,
                        choice_sequence=route.edges,
                    )
                )

        elif act is Act.CUSTODY_PRESUPPOSITION:
            # L7：共用结尾预设“保管得真稳”，要求持有关系仍成立且交付没被收回
            handover = state.latest_valid(f"handover:{KEY_ITEM}")
            if handover is None or state.key_holder != HOLDER_YUZHOU:
                findings.append(
                    Finding(
                        "PRESUPPOSITION-FAILS",
                        SEVERITY_BLOCK,
                        route.route_id,
                        line.scene,
                        line.id,
                        None,
                        "共用结尾的保管预设在这条来路上不成立：没有可追溯的有效交付",
                        tuple(
                            fact.source_line
                            for fact in state.facts
                            if "handover" in fact.fact_key
                            or fact.fact_key == "promise:conditional_key_custody"
                        ),
                        choice_sequence=route.edges,
                    )
                )

        elif act is Act.UNKNOWN:
            findings.append(
                Finding(
                    "LINE-UNCLASSIFIED",
                    SEVERITY_QUESTION,
                    route.route_id,
                    line.scene,
                    line.id,
                    None,
                    f"台词 {line.id} 无法按现有规则判定行为，需要编剧按原话确认",
                    (line.id,),
                    confirm_key=state.context_key(line, "unclassified_reading"),
                    choice_sequence=route.edges,
                )
            )
    return findings


def _hearsay_vs_direct_note(
    route: Route, classifications: Mapping[str, Classification], script: Script
) -> list[Finding]:
    """“她说他把信交了”式转述与本人交付承诺必须保留不同依据，这里做显式核对。"""

    findings: list[Finding] = []
    state = route.state
    reports = state.facts_of(f"report:handover:{KEY_ITEM}")
    direct = state.valid_facts(f"handover:{KEY_ITEM}")
    if reports:
        findings.append(
            Finding(
                "HEARSAY-KEPT-SEPARATE",
                SEVERITY_NOTE,
                route.route_id,
                state.scene or "",
                reports[-1].source_line,
                None,
                "转述依据已与直接交付分层保存：转述只证明有人这样说过，不证明钥匙已交接"
                + ("；本路线另有直接交付。" if direct else "；本路线没有直接交付。"),
                tuple(f.source_line for f in reports)
                + tuple(f.source_line for f in direct),
                choice_sequence=route.edges,
            )
        )
    return findings


def review_script(
    script: Script,
    *,
    entry: str | None = None,
    walk_result: WalkResult | None = None,
) -> ReviewReport:
    walked = walk_result or walk(script, entry)
    findings: list[Finding] = []

    for route in walked.routes:
        findings.extend(_trigger_findings(route))
        findings.extend(_line_findings(script, route, walked.classifications))
        findings.extend(_hearsay_vs_direct_note(route, walked.classifications, script))
    findings.extend(_dead_edge_findings(script, walked))

    questions = tuple(item for item in findings if item.severity == SEVERITY_QUESTION)
    compatibilities = _compatibility(script, walked.routes, walked.classifications)

    return ReviewReport(
        findings=tuple(findings),
        questions=questions,
        compatibilities=tuple(compatibilities),
        pruned_loops=tuple(walked.pruned),
        routes=tuple(walked.routes),
        classifications=walked.classifications,
    )


def _compatibility(
    script: Script,
    routes: Sequence[Route],
    classifications: Mapping[str, Classification],
) -> list[Compatibility]:
    """共用场景候选台词 × 所有实际走到该场景的来路。

    判断依据是候选台词播出的那一次到访之前、该场景检查点上的局部状态，
    而不是整条路线的累计事实——同一房间第二次到访不等于第一次。
    """

    result: list[Compatibility] = []
    shared_groups = {
        key: group
        for key, group in script.variant_groups().items()
        if len(group) > 1 or key[0] in {"S6", "S4"}
    }

    for key, group in sorted(shared_groups.items()):
        scene_id = key[0]
        arrivals = [route for route in routes if scene_id in route.scenes]
        if not arrivals:
            continue
        for line in group:
            viable: list[str] = []
            broken: list[tuple[str, tuple[str, ...]]] = []
            for route in arrivals:
                if _line_viable_on_route(line, route, classifications):
                    viable.append(route.route_id)
                else:
                    broken.append((route.route_id, route.edges))
            result.append(
                Compatibility(
                    scene_id,
                    line.id,
                    line.quote,
                    tuple(viable),
                    tuple(broken),
                    works_everywhere=not broken,
                )
            )
    return result


def _line_viable_on_route(
    line: Line,
    route: Route,
    classifications: Mapping[str, Classification],
) -> bool:
    """假设在该来路的本次到访采用这句台词，依据是否成立。"""

    act = classifications[line.id].act
    state = route.state
    # 该场景最后一次到访前的局部状态
    checkpoints = state.checkpoints.get(line.scene, ())
    before = checkpoints[-1] if checkpoints else state

    if act is Act.HANDOVER:
        # 本次到访之前要有仍有效的许诺或接受作为托付依据；
        # 曾被收回不禁止重新交付（第二次到访的 L3 就是重新托付）
        had_promise = bool(before.valid_facts("promise:conditional_key_custody"))
        had_acceptance = bool(before.valid_facts("acceptance:stay_and_hold"))
        return had_promise or had_acceptance
    if act is Act.REFUSAL:
        # 反向承诺要求本次到访之前存在可被反转的承诺或交付（含已失效的历史）
        had_promise = bool(before.facts_of("promise:conditional_key_custody"))
        had_handover = bool(before.facts_of(f"handover:{KEY_ITEM}"))
        return had_promise or had_handover
    if act is Act.CUSTODY_PRESUPPOSITION:
        handover = state.latest_valid(f"handover:{KEY_ITEM}")
        return handover is not None and state.key_holder == HOLDER_YUZHOU
    if act is Act.ACTION_CLAIM:
        handover = state.latest_valid(f"handover:{KEY_ITEM}")
        return handover is not None and state.key_holder == HOLDER_YUZHOU
    if act is Act.NEUTRAL:
        return True
    return True


def apply_confirmations(
    report: ReviewReport, confirmations: Mapping[str, str]
) -> ReviewReport:
    """套用编剧确认。

    确认值：
    - "accepted"：编剧按具体台词与分支确认该读法；仅消解问题，不新增事实。
    - "rejected"：编剧否定该读法，问题升级为阻断。
    上下文签名不符的确认键一律拒绝复用。
    """

    valid_keys = {
        finding.confirm_key
        for finding in report.findings
        if finding.confirm_key is not None
    }
    unknown = sorted(set(confirmations) - valid_keys)
    if unknown:
        raise KeyError(f"确认键与当前剧本上下文不匹配，拒绝复用：{unknown}")

    findings: list[Finding] = []
    for finding in report.findings:
        answer = confirmations.get(finding.confirm_key or "")
        if answer not in ("accepted", "rejected"):
            findings.append(finding)
        elif answer == "accepted":
            findings.append(
                Finding(
                    finding.code,
                    SEVERITY_NOTE,
                    finding.route_id,
                    finding.scene,
                    finding.line_id,
                    finding.edge_id,
                    f"[编剧已确认读法] {finding.message}",
                    finding.evidence,
                    confirm_key=finding.confirm_key,
                    choice_sequence=finding.choice_sequence,
                )
            )
        else:
            findings.append(
                Finding(
                    finding.code,
                    SEVERITY_BLOCK,
                    finding.route_id,
                    finding.scene,
                    finding.line_id,
                    finding.edge_id,
                    f"[编剧否定该读法] {finding.message}",
                    finding.evidence,
                    confirm_key=finding.confirm_key,
                    choice_sequence=finding.choice_sequence,
                )
            )

    return ReviewReport(
        findings=tuple(findings),
        questions=tuple(item for item in findings if item.severity == SEVERITY_QUESTION),
        compatibilities=report.compatibilities,
        pruned_loops=report.pruned_loops,
        routes=report.routes,
        classifications=report.classifications,
    )


def knowledge_matrix(script: Script, state: RouteState) -> dict[str, list[dict[str, str]]]:
    """谁知道谁说过什么：按角色输出其掌握的事实与依据等级。"""

    matrix: dict[str, list[dict[str, str]]] = {}
    for role in script.roles:
        entries: list[dict[str, str]] = []
        for fact in state.knowledge.get(role.id, ()):
            entries.append(
                {
                    "fact": fact.fact_key,
                    "claim": fact.claim,
                    "source_line": fact.source_line,
                    "basis": fact.basis.value,
                    "valid": str(fact.valid),
                }
            )
        matrix[role.id] = entries
    return matrix


def promise_dossier(script: Script, state: RouteState) -> dict[str, object]:
    """编剧追踪用：附条件许诺的完整案卷与兑现幕次。"""

    verdict, anchor = state.promise_status()
    return {
        "verdict": verdict.value,
        "anchor_line": anchor.source_line if anchor else None,
        "custody_evidence_scene": state.custody_evidence_scene(),
        "key_holder": state.key_holder,
        "timeline": [
            {
                "scene": scene,
                "holder": holder,
                "source_line": line_id,
            }
            for scene, holder, line_id in state.key_history
        ],
        "facts": [
            {
                "key": fact.fact_key,
                "source_line": fact.source_line,
                "basis": fact.basis.value,
                "valid": fact.valid,
                "note": fact.note,
            }
            for fact in state.facts
        ],
    }
