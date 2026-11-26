"""交片评估。

规则对应后期流程：

1. 授权以 release.rights 为准；languages 超出 rights 在加载期即报错。
2. 音轨 ready 只表示素材齐备，不赋予剧本有效性；阻断依据来自 review 的 findings。
3. 某条路要靠新台词修好而该句未录好，只阻断依赖它的路线，已制片路线继续交付。
4. 每个对观众开放的 option，其后必须真有可播放的下一段；
   不能只封音轨却留下能点进空片的按钮——不可播放的边应从片单选项中关闭。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .graph import Route
from .model import Release, Script
from .review import (
    SEVERITY_BLOCK,
    SEVERITY_QUESTION,
    Finding,
    ReviewReport,
    review_script,
)


@dataclass(frozen=True)
class LineStatus:
    line_id: str
    language: str
    ready: bool
    track_id: str | None


@dataclass(frozen=True)
class RouteVerdict:
    route_id: str
    language: str
    deliverable: bool
    edges: tuple[str, ...]
    scenes: tuple[str, ...]
    played_lines: tuple[str, ...]
    blocking_findings: tuple[Finding, ...]
    missing_tracks: tuple[LineStatus, ...]
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class OptionCheck:
    edge_id: str
    keep_open: bool
    playable_routes: tuple[str, ...]
    reason: str


@dataclass(frozen=True)
class ReleaseReport:
    release_id: str
    planned_languages: tuple[str, ...]
    authorized_languages: tuple[str, ...]
    unauthorized_planned: tuple[str, ...]
    route_verdicts: tuple[RouteVerdict, ...]
    options: tuple[OptionCheck, ...]
    # 仍需重录的句子（按语言去重），与已完成版本分开列
    re_record: tuple[LineStatus, ...]
    ready_tracks: tuple[LineStatus, ...]
    deliverable_route_count: int
    blocked_route_count: int


def line_status(script: Script, line_id: str, language: str) -> LineStatus:
    tracks = [track for track in script.tracks_for(line_id) if track.language == language]
    ready = any(track.ready for track in tracks)
    track_id = next((track.id for track in tracks if track.ready), None) or (
        tracks[0].id if tracks else None
    )
    return LineStatus(line_id, language, ready, track_id)


def _routes_using_release_options(
    routes: Sequence[Route], release: Release
) -> list[Route]:
    allowed = set(release.options)
    return [route for route in routes if set(route.edges) <= allowed]


def assess_release(
    script: Script,
    release: Release,
    review: ReviewReport,
) -> ReleaseReport:
    allowed_routes = _routes_using_release_options(review.routes, release)
    block_by_route: dict[str, list[Finding]] = {}
    question_by_route: dict[str, list[Finding]] = {}
    for finding in review.findings:
        if finding.severity == SEVERITY_BLOCK:
            block_by_route.setdefault(finding.route_id, []).append(finding)
        elif finding.severity == SEVERITY_QUESTION:
            question_by_route.setdefault(finding.route_id, []).append(finding)

    verdicts: list[RouteVerdict] = []
    re_record: dict[tuple[str, str], LineStatus] = {}
    ready: dict[tuple[str, str], LineStatus] = {}

    for route in allowed_routes:
        played = tuple(dict.fromkeys(route.state.line_events))
        # 交片判定只覆盖授权语言；计划但未授权的语言不进交付/重录清单
        evaluated_languages = release.rights
        for language in evaluated_languages:
            authorized = language in release.rights
            blockers = list(block_by_route.get(route.route_id, ()))
            # 待确认读法同样不允许直接交片
            blockers.extend(question_by_route.get(route.route_id, ()))
            missing: list[LineStatus] = []
            for line_id in played:
                status = line_status(script, line_id, language)
                bucket = ready if status.ready else re_record
                bucket[(line_id, language)] = status
                if not status.ready:
                    missing.append(status)
            reasons = tuple(
                f"[{finding.code}] {finding.message}" for finding in blockers
            ) + tuple(
                f"[TRACK-MISSING] {status.line_id} 缺少 {status.language} 就绪音轨"
                for status in missing
            )
            verdicts.append(
                RouteVerdict(
                    route_id=route.route_id,
                    language=language,
                    deliverable=authorized and not blockers and not missing,
                    edges=route.edges,
                    scenes=route.scenes,
                    played_lines=played,
                    blocking_findings=tuple(blockers),
                    missing_tracks=tuple(missing),
                    reasons=reasons,
                )
            )

    # 按钮一致性：开放选项后必须至少有一条该语言可播放路线经过它。
    # 判定分两层：依据断裂（findings）必须关按钮；仅音轨待录时，只要该选项的
    # 后继段落存在改用已录候选的可播路线，按钮仍可开放，不能只封音轨留下空按钮。
    option_checks: list[OptionCheck] = []
    grounded_edges = {
        edge_id
        for verdict in verdicts
        if not verdict.blocking_findings
        for edge_id in verdict.edges
    }
    for edge_id in release.options:
        playable = {
            verdict.route_id
            for verdict in verdicts
            if verdict.deliverable and edge_id in verdict.edges
        }
        if playable:
            reason = "存在可播放后继段落，保持开放"
            keep = True
        elif edge_id in grounded_edges:
            reason = (
                "依据成立但后继台词仍待重录；按钮可保留，交片前必须补齐音轨，"
                "不得放出指向未录段落的入口"
            )
            keep = True
        else:
            reason = (
                "没有任何依据成立的可播放路线经过该选项；"
                "应从片单关闭此按钮，避免点进空片或依据断裂段落"
            )
            keep = False
        option_checks.append(
            OptionCheck(edge_id, keep, tuple(sorted(playable)), reason)
        )

    deliverable = sum(1 for verdict in verdicts if verdict.deliverable)
    return ReleaseReport(
        release.id,
        tuple(release.languages),
        release.rights,
        tuple(sorted(set(release.languages) - set(release.rights))),
        tuple(verdicts),
        tuple(option_checks),
        tuple(re_record.values()),
        tuple(ready.values()),
        deliverable,
        len(verdicts) - deliverable,
    )


def assess_all(script: Script) -> tuple[ReviewReport, dict[str, ReleaseReport]]:
    review = review_script(script)
    reports = {
        release.id: assess_release(script, release, review)
        for release in script.releases
    }
    return review, reports
