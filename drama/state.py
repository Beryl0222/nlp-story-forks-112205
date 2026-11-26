"""沿单条路线累积的认知与持有状态。

设计原则：

1. 每个事实都带依据：direct（当事人在场原话）/hearsay（转述）/retracted（改口否认）。
2. 回到同一房间不清空历史：新事件只追加；收回/拒绝会让旧承诺失效，但旧记录仍可追溯。
3. 触发条件由状态回答；证据不足时不默默放行，而是生成带上下文签名的待确认问题。
4. 状态签名只保留会改变后续判断的差异，供图遍历剪枝使用。
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Mapping, Sequence

from .acts import Act, Basis, Classification
from .model import Edge, Line, Script

# 《望潮楼》固定物件与人物：楼钥匙的托付链围绕 R1→R2
KEY_ITEM = "building_key"
OWNER_AQIN = "R1"
HOLDER_YUZHOU = "R2"
KEEPER_HUASHU = "R3"


class Verdict(str, Enum):
    OPEN = "open"          # 仍有效
    FULFILLED = "fulfilled"  # 已兑现（找到实际交付/使用证据的那一幕）
    REVOKED = "revoked"    # 被收回或反向承诺终止
    RETRACTED = "retracted"  # 听错改口，自始不成立


@dataclass(frozen=True)
class Fact:
    """一条登记事实。同一 fact_key 可有多条，按时间排列，最新有效者为准。"""

    fact_key: str
    claim: str
    source_line: str
    basis: Basis
    valid: bool = True
    note: str = ""

    @property
    def signature(self) -> tuple[str, str, str, bool]:
        return (self.fact_key, self.source_line, self.basis.value, self.valid)


@dataclass(frozen=True)
class TriggerResult:
    edge: Edge
    satisfied: bool
    evidence: tuple[str, ...]
    question_key: str | None = None
    question: str | None = None


@dataclass(frozen=True)
class RouteState:
    script: Script
    visits: tuple[str, ...] = ()
    edge_path: tuple[str, ...] = ()
    line_events: tuple[str, ...] = ()              # 实际生效的台词 id（含变体）
    # 变体选择：键 (scene,line_no) 作用于首次到访，(scene,line_no,visit) 精确到第几次
    chosen_variants: Mapping[tuple, str] = field(default_factory=dict)
    # 每次进入场景时、该幕台词应用前的状态检查点，供局部兼容性判断
    checkpoints: Mapping[str, tuple["RouteState", ...]] = field(default_factory=dict)
    facts: tuple[Fact, ...] = ()
    knowledge: Mapping[str, tuple[Fact, ...]] = field(default_factory=dict)
    key_holder: str | None = OWNER_AQIN
    key_history: tuple[tuple[str, str, str], ...] = ()  # (场景, 持有人, 台词)
    open_questions: tuple[str, ...] = ()

    # ---- 基础派生 ----

    @property
    def scene(self) -> str | None:
        return self.visits[-1] if self.visits else None

    @property
    def visit_count(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for scene in self.visits:
            counts[scene] = counts.get(scene, 0) + 1
        return counts

    def facts_of(self, fact_key: str) -> tuple[Fact, ...]:
        return tuple(f for f in self.facts if f.fact_key == fact_key)

    def valid_facts(self, fact_key: str) -> tuple[Fact, ...]:
        return tuple(f for f in self.facts if f.fact_key == fact_key and f.valid)

    def latest_valid(self, fact_key: str) -> Fact | None:
        items = self.valid_facts(fact_key)
        return items[-1] if items else None

    def knows(self, role_id: str, fact_key: str) -> tuple[Fact, ...]:
        return tuple(
            f for f in self.knowledge.get(role_id, ()) if f.fact_key == fact_key
        )

    def knows_valid(self, role_id: str, fact_key: str) -> tuple[Fact, ...]:
        return tuple(
            f
            for f in self.knowledge.get(role_id, ())
            if f.fact_key == fact_key and f.valid
        )

    # ---- 承诺与持有查询（编剧追踪用）----

    def promise_status(self) -> tuple[Verdict, Fact | None]:
        """附条件许诺 L1 当前效力。

        收回（L9）会把许诺事实置为无效，因此吊销判断不能依赖许诺仍有效，
        必须先独立查吊销事实；完整历史仍保留在 facts 中可追溯。
        """

        revocation = self.latest_valid("revocation:conditional_key_custody")
        if revocation is not None:
            return Verdict.REVOKED, revocation
        promise = self.latest_valid("promise:conditional_key_custody")
        if promise is None:
            return Verdict.OPEN, None
        handover = self.latest_valid(f"handover:{KEY_ITEM}")
        if handover is not None:
            return Verdict.FULFILLED, handover
        return Verdict.OPEN, promise

    def custody_evidence_scene(self) -> str | None:
        """第一处能证明“余舟实际持有钥匙”的场景。"""

        for scene, holder, line_id in self.key_history:
            if holder == HOLDER_YUZHOU:
                return scene
        return None

    def _current_markers(self) -> tuple[tuple[str, str, str], ...]:
        """按 fact_key 归并后的当前有效事实（同 key 只留最新一条）。"""

        latest: dict[str, Fact] = {}
        for fact in self.facts:
            if fact.valid:
                latest[fact.fact_key] = fact
        return tuple(
            sorted(
                (key, fact.source_line, fact.basis.value)
                for key, fact in latest.items()
            )
        )

    def judgement_signature(self) -> str:
        """剪枝签名：只纳入会改变后续判断的当前有效状态。

        访问次数与历史轨迹不进签名——同样的持有/承诺/认知结论下再点一次返回，
        不产生新的待审路线；完整时间线仍保留在 facts/key_history 里可追溯。
        """

        known: dict[str, set[tuple[str, str, str]]] = {}
        for role, facts in self.knowledge.items():
            latest: dict[str, Fact] = {}
            for fact in facts:
                if fact.valid:
                    latest[fact.fact_key] = fact
            known[role] = {
                (key, fact.source_line, fact.basis.value)
                for key, fact in latest.items()
            }
        payload = (
            self.scene,
            self.key_holder,
            self._current_markers(),
            tuple((role, tuple(sorted(markers))) for role, markers in sorted(known.items())),
            tuple(sorted(self.open_questions)),
        )
        digest = hashlib.sha256(repr(payload).encode("utf-8")).hexdigest()[:16]
        return f"{self.scene or 'ENTRY'}:{digest}"

    def context_key(self, line: Line, question_id: str) -> str:
        """待确认问题的上下文键。

        同一台词在判断相关上下文真正相同的重复出现位置才复用同一确认；
        第二次到访若已有不同历史，键必然不同。
        """

        context = (
            line.id,
            question_id,
            self.scene,
            self.visit_count.get(line.scene, 0),
            tuple(sorted(f.signature for f in self.facts)),
            self.key_holder,
        )
        digest = hashlib.sha256(repr(context).encode("utf-8")).hexdigest()[:12]
        return f"confirm:{line.id}:{question_id}@{digest}"


# ---- 台词应用 ----


def initial_state(script: Script, entry: str) -> RouteState:
    return RouteState(script=script, visits=(entry,))


def _learn(state: RouteState, roles: Sequence[str], fact: Fact) -> dict[str, tuple[Fact, ...]]:
    knowledge = {role: tuple(facts) for role, facts in state.knowledge.items()}
    for role in roles:
        knowledge[role] = (*knowledge.get(role, ()), fact)
    return knowledge


def _invalidate_fact(facts: Sequence[Fact], fact_key: str, note: str) -> list[Fact]:
    updated: list[Fact] = []
    for fact in facts:
        if fact.fact_key == fact_key and fact.valid:
            updated.append(replace(fact, valid=False, note=note))
        else:
            updated.append(fact)
    return updated


def apply_line(
    state: RouteState, line: Line, classification: Classification
) -> RouteState:
    """把一句台词的效果落到路线状态上。返回新状态（原状态不变）。"""

    scene = state.scene or line.scene
    facts = list(state.facts)
    knowledge = {role: tuple(items) for role, items in state.knowledge.items()}
    holder = state.key_holder
    history = list(state.key_history)
    listeners = list(line.listeners)
    audience = [line.speaker, *listeners]

    def add(fact: Fact, learned_by: Sequence[str]) -> None:
        facts.append(fact)
        knowledge.update(_learn(state, learned_by, fact))

    if classification.act is Act.CONDITIONAL_PROMISE:
        fact = Fact(
            "promise:conditional_key_custody",
            "若余舟留下，阿芹替花叔保管钥匙（附条件许诺，未交付）",
            line.id,
            Basis.DIRECT,
            note="许诺不是交付",
        )
        add(fact, audience)

    elif classification.act is Act.ACCEPTANCE:
        fact = Fact(
            "acceptance:stay_and_hold",
            "余舟答应留下并愿意接手钥匙",
            line.id,
            Basis.DIRECT,
        )
        add(fact, audience)

    elif classification.act is Act.HANDOVER:
        # 当事人亲自交付：直接依据，同时兑现此前的附条件许诺
        fact = Fact(
            f"handover:{KEY_ITEM}",
            "阿芹当面把楼钥匙托给余舟",
            line.id,
            Basis.DIRECT,
        )
        add(fact, audience)
        holder = HOLDER_YUZHOU
        history.append((scene, holder, line.id))

    elif classification.act is Act.TAKEBACK:
        revoked = Fact(
            "revocation:conditional_key_custody",
            "阿芹收回前言并收回钥匙",
            line.id,
            Basis.DIRECT,
        )
        add(revoked, audience)
        facts = _invalidate_fact(facts, "promise:conditional_key_custody", "被 L9 式收回终止")
        facts = _invalidate_fact(facts, f"handover:{KEY_ITEM}", "钥匙已被收回")
        holder = OWNER_AQIN
        history.append((scene, holder, line.id))

    elif classification.act is Act.REFUSAL:
        refusal = Fact(
            "refusal:second_visit",
            "第二次到访时阿芹反向承诺，这回先不给钥匙",
            line.id,
            Basis.DIRECT,
        )
        add(refusal, audience)
        # 反向承诺不抹掉历史交付记录，但当前持有回到阿芹
        if holder == HOLDER_YUZHOU:
            holder = OWNER_AQIN
            history.append((scene, holder, line.id))

    elif classification.act is Act.MISHEARD_RETRACTION:
        # 先登记错误复述（转述依据），随即由本人否认；
        # 只失效本句自己的错误复述，不波及 L4 等他人此前的澄清
        hearsay = Fact(
            f"report:handover:{KEY_ITEM}",
            "余舟一度复述“她说她给我了”",
            line.id,
            Basis.HEARSAY,
            valid=False,
            note="本人随即改口：听岔了",
        )
        add(hearsay, audience)
        retraction = Fact(
            "retraction:handover_belief",
            "余舟否认钥匙已交接，先前听来的说法不成立",
            line.id,
            Basis.RETRACTED,
        )
        add(retraction, audience)
        facts = [
            replace(fact, valid=False, note="听错后改口")
            if fact.fact_key == f"report:handover:{KEY_ITEM}"
            and fact.valid
            and fact.source_line == line.id
            else fact
            for fact in facts
        ]
        # 任何“余舟相信已交接”的残留信念一并失效
        facts = _invalidate_fact(facts, "belief:handover:building_key", "听错后改口")

    elif classification.act is Act.REPORT:
        # 花叔式澄清：只证明“有过若留下便保管的说法”，不证明交付
        report = Fact(
            f"report:handover:{KEY_ITEM}",
            "守楼人澄清：没说过钥匙已经交了",
            line.id,
            Basis.HEARSAY,
            note="转述与交付事实分层保存",
        )
        add(report, audience)

    elif classification.act is Act.ACTION_CLAIM:
        fact = Fact(
            "action:open_with_key",
            "余舟主张用刚交到手里的钥匙开门",
            line.id,
            Basis.DIRECT,
        )
        add(fact, audience)
        # 行动主张不改变持有关系；仅当确实持有时才在持有链留一幕可核对记录，
        # 无钥匙的错误主张不污染时间线（其不成立由 review 阻断）
        if holder == HOLDER_YUZHOU:
            history.append((scene, holder, line.id))

    elif classification.act is Act.CUSTODY_PRESUPPOSITION:
        fact = Fact(
            "presupposition:custody_steady",
            "共用结尾预设余舟一直稳妥保管钥匙",
            line.id,
            Basis.DIRECT,
        )
        add(fact, audience)

    elif classification.act is Act.NEUTRAL:
        pass  # 中性台词不产生事实

    else:
        # UNKNOWN：不产生任何事实，由 review 挂出待确认
        pass

    return replace(
        state,
        facts=tuple(facts),
        knowledge=knowledge,
        key_holder=holder,
        key_history=tuple(history),
        line_events=(*state.line_events, line.id),
    )


def _select_scene_lines(
    script: Script,
    scene_id: str,
    chosen_variants: Mapping[tuple, str],
    visit_number: int,
) -> tuple[Line, ...]:
    """每个 (scene,line_no) 候选组只保留一条。

    选择优先级：精确到访键 (scene,line_no,visit) > 首次到访通用键 (scene,line_no)
    （仅当 visit=1）> 默认稿。
    """

    selected: list[Line] = []
    for group in script.variant_groups().values():
        base = next((line for line in group if line.scene == scene_id), None)
        if base is None:
            continue
        specific = chosen_variants.get((*base.key, visit_number))
        general = chosen_variants.get(base.key) if visit_number == 1 else None
        chosen_id = specific if specific is not None else general
        if chosen_id is None:
            default = next((line for line in group if not line.is_variant), group[0])
            selected.append(default)
        else:
            picked = next((line for line in group if line.id == chosen_id), None)
            if picked is None:
                raise ValueError(f"变体选择 {chosen_id} 在 {base.key} 候选组中不存在")
            selected.append(picked)
    return tuple(sorted(selected, key=lambda line: line.line_no))


def enter_scene(
    state: RouteState,
    scene_id: str,
    classifications: Mapping[str, Classification],
    chosen_variants: Mapping[tuple, str] | None = None,
) -> RouteState:
    """进入场景：登记访问，再按 line_no 顺序应用该场景应播的台词。

    同 line_no 的变体互斥；未显式选择时播默认稿。到访次序由既有访问记录推出，
    因此同一房间第二次到访可以选择与第一次不同的台词。
    """

    choices = chosen_variants or state.chosen_variants
    visit_number = state.visit_count.get(scene_id, 0) + 1
    checkpoint = replace(
        state,
        visits=(*state.visits, scene_id),
        chosen_variants={**state.chosen_variants, **choices},
    )
    previous = state.checkpoints.get(scene_id, ())
    moved = replace(
        checkpoint,
        checkpoints={**state.checkpoints, scene_id: (*previous, checkpoint)},
    )
    for line in _select_scene_lines(state.script, scene_id, choices, visit_number):
        moved = apply_line(moved, line, classifications[line.id])
    return moved


# ---- 触发条件 ----


def evaluate_trigger(
    state: RouteState, edge: Edge, classifications: Mapping[str, Classification]
) -> TriggerResult:
    """依据当前路线状态判断边的 trigger 是否成立。"""

    trigger = edge.trigger

    if trigger == "任何时候":
        return TriggerResult(edge, True, ())

    if trigger == "余舟答应留下":
        fact = state.latest_valid("acceptance:stay_and_hold")
        if fact is not None:
            return TriggerResult(edge, True, (fact.source_line,))
        return TriggerResult(edge, False, ())

    if trigger == "没有请余舟守候":
        # 该分支的成立条件恰恰是不存在“答应留下”的接受事实
        fact = state.latest_valid("acceptance:stay_and_hold")
        if fact is None:
            return TriggerResult(edge, True, ("absence:acceptance:stay_and_hold",))
        return TriggerResult(edge, False, (fact.source_line,))

    if trigger == "余舟手里有楼钥匙":
        if state.key_holder == HOLDER_YUZHOU:
            evidence = tuple(
                line_id for _, holder, line_id in state.key_history if holder == HOLDER_YUZHOU
            )
            return TriggerResult(edge, True, evidence[-1:] or ("state:holder",))
        return TriggerResult(edge, False, ())

    if trigger == "余舟相信钥匙已交接":
        # 信念必须来自仍然有效的依据；听错改口后的残留信念不算数
        direct = state.valid_facts(f"handover:{KEY_ITEM}")
        belief = state.knows_valid(HOLDER_YUZHOU, "belief:handover:building_key")
        retractions = state.facts_of("retraction:handover_belief")
        if (direct or belief) and not retractions:
            return TriggerResult(
                edge, True, tuple(f.source_line for f in (*direct, *belief))
            )
        # 存在两种读法且会改变 E4 这个后续选择：交给编剧按具体台词确认
        hearsay = state.facts_of(f"report:handover:{KEY_ITEM}")
        retractions = state.facts_of("retraction:handover_belief")
        if hearsay or retractions:
            anchor_ids = {fact.source_line for fact in (*hearsay, *retractions)}
            candidates = [
                state.script.line(line_id) for line_id in anchor_ids
            ]
            # 固定取来源台词中 line_no 最小者作为锚点，保证键可复现
            anchor = min(candidates, key=lambda line: (line.scene, line.line_no, line.variant))
            key = state.context_key(anchor, "belief_after_retraction")
            question = (
                f"{anchor.id} 所在上下文（{anchor.scene} 第 {anchor.line_no} 句）里，"
                "余舟是否仍可被读作相信钥匙已交接？现有直接交付依据为空，"
                "且听错改口在案；确认只能解决读法，不能补出交付事实。"
            )
            return TriggerResult(edge, False, (), key, question)
        return TriggerResult(edge, False, ())

    if trigger == "开门完成":
        fact = state.latest_valid("action:open_with_key")
        if fact is not None and state.key_holder == HOLDER_YUZHOU:
            return TriggerResult(edge, True, (fact.source_line,))
        return TriggerResult(edge, False, ())

    if trigger in ("暂时离开", "重新与余舟商量"):
        # 结构性回头路，不要求钥匙依据
        return TriggerResult(edge, True, ())

    # 未登记的 trigger 不猜测
    return TriggerResult(
        edge,
        False,
        (),
        f"confirm:trigger:{edge.id}:unknown",
        f"边 {edge.id} 的触发原话“{trigger}”没有判定规则，需要编剧确认。",
    )
