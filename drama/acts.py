"""台词行为分类。

分类规则显式登记在 RULES 中，按顺序匹配；匹配不到的台词标记为 UNKNOWN，
交给编剧确认，绝不静默套用某种行为。每条规则同时声明该台词提供的依据强度：

- DIRECT    当事人在场原话，可作为事实/承诺/交付的直接依据
- HEARSAY   转述他人的话，只证明“有人这样说过”，不证明被转述的事实
- RETRACTED 听错后的改口，先抹掉此前错误复述再记录否认
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable, Sequence

from .model import Line, Script, role_by_term


class Act(str, Enum):
    CONDITIONAL_PROMISE = "conditional_promise"  # 附条件许诺
    ACCEPTANCE = "acceptance"                    # 接受附条件托付
    HANDOVER = "handover"                        # 当事人亲自交付
    TAKEBACK = "takeback"                        # 收回钥匙/收回前言
    REFUSAL = "refusal"                          # 改口拒绝交付
    MISHEARD_RETRACTION = "misheard_retraction"  # 听错之后的复述与否认
    REPORT = "report"                            # 第三方转述
    ACTION_CLAIM = "action_claim"                # 对既成动作的主张（用钥匙开门）
    CUSTODY_PRESUPPOSITION = "custody_presupposition"  # 共用结尾对持有关系的预设
    NEUTRAL = "neutral"                          # 不改变任何依据的台词
    UNKNOWN = "unknown"


class Basis(str, Enum):
    DIRECT = "direct"
    HEARSAY = "hearsay"
    RETRACTED = "retracted"
    NONE = "none"


@dataclass(frozen=True)
class Classification:
    line: Line
    act: Act
    basis: Basis
    rule_id: str
    rule_note: str


@dataclass(frozen=True)
class Rule:
    rule_id: str
    act: Act
    basis: Basis
    note: str
    predicate: Callable[[Line, Script], bool]


def _contains(text: str, *fragments: str) -> bool:
    return all(fragment in text for fragment in fragments)


def _speaker_known(line: Line, script: Script, *terms: str) -> bool:
    role = script.role(line.speaker)
    return any(term in role.all_terms for term in terms)


def _mentions_any_role(line: Line, script: Script, *terms: str) -> bool:
    text = line.quote
    for term in terms:
        role = role_by_term(script, term)
        if role is not None and any(alias in text for alias in role.all_terms):
            return True
    return False


# 顺序即优先级：先抓带明确动作/改口特征的，再抓许诺与转述。
RULES: tuple[Rule, ...] = (
    Rule(
        "A-HANDOVER",
        Act.HANDOVER,
        Basis.DIRECT,
        "出现“托给你/交给你”等当面交付措辞，且语内指明钥匙落到对方手里；"
        "“用你刚交给我的钥匙开门”是行动主张而非新交付，由 A-ACTION-CLAIM 处理",
        lambda line, script: (
            _contains(line.quote, "托给你")
            or (
                _contains(line.quote, "交")
                and _contains(line.quote, "钥匙")
                and _contains(line.quote, "你")
                and "没" not in line.quote
                and "不" not in line.quote
                and not _contains(line.quote, "用", "开")
            )
        ),
    ),
    Rule(
        "A-TAKEBACK",
        Act.TAKEBACK,
        Basis.DIRECT,
        "明确宣布收回前言并收回钥匙",
        lambda line, script: _contains(line.quote, "收回"),
    ),
    Rule(
        "A-REFUSAL",
        Act.REFUSAL,
        Basis.DIRECT,
        "再次到访时作出反向承诺，拒绝交付",
        lambda line, script: _contains(line.quote, "先不给你"),
    ),
    Rule(
        "A-MISHEARD",
        Act.MISHEARD_RETRACTION,
        Basis.RETRACTED,
        "先复述听来的说法，随即自行否认（听岔）",
        lambda line, script: _contains(line.quote, "听岔"),
    ),
    Rule(
        "A-REPORT-CORRECTION",
        Act.REPORT,
        Basis.HEARSAY,
        "第三方澄清“没说已经交了”，转述与事实分层",
        lambda line, script: _contains(line.quote, "没说")
        and _contains(line.quote, "交"),
    ),
    Rule(
        "A-ACTION-CLAIM",
        Act.ACTION_CLAIM,
        Basis.DIRECT,
        "当事人主张自己正在用交来的钥匙开门",
        lambda line, script: _contains(line.quote, "用")
        and _contains(line.quote, "钥匙")
        and _contains(line.quote, "开"),
    ),
    Rule(
        "A-CUSTODY-PRESUPPOSITION",
        Act.CUSTODY_PRESUPPOSITION,
        Basis.DIRECT,
        "共用结尾预设对方一直保管着钥匙，要求持有关系仍然成立",
        lambda line, script: _contains(line.quote, "保管")
        and _contains(line.quote, "稳"),
    ),
    Rule(
        "A-ACCEPTANCE",
        Act.ACCEPTANCE,
        Basis.DIRECT,
        "听者明确答应留下，并愿意在对方不在时接手",
        lambda line, script: _contains(line.quote, "留下")
        and _contains(line.quote, "交给我"),
    ),
    Rule(
        "A-CONDITIONAL-PROMISE",
        Act.CONDITIONAL_PROMISE,
        Basis.DIRECT,
        "“你若……我会……”式附条件许诺，只登记承诺，不登记交付",
        lambda line, script: ("若" in line.quote or "你不在" in line.quote)
        and _contains(line.quote, "保管"),
    ),
    Rule(
        "A-NEUTRAL",
        Act.NEUTRAL,
        Basis.NONE,
        "不主张任何事实或持有关系的中性台词",
        lambda line, script: _contains(line.quote, "望潮"),
    ),
)


def classify(line: Line, script: Script) -> Classification:
    for rule in RULES:
        if rule.predicate(line, script):
            return Classification(line, rule.act, rule.basis, rule.rule_id, rule.note)
    return Classification(
        line,
        Act.UNKNOWN,
        Basis.NONE,
        "A-UNKNOWN",
        "没有规则命中，需要编剧按原话确认其行为与依据",
    )


def classify_all(script: Script) -> dict[str, Classification]:
    return {line.id: classify(line, script) for line in script.lines}


def classifications_at(
    script: Script, scene_id: str
) -> Sequence[tuple[Line, Classification]]:
    table = classify_all(script)
    return [(line, table[line.id]) for line in script.lines_at(scene_id)]
