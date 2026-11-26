"""命令行入口：python -m drama <command>。"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Sequence

from .graph import trace, walk
from .loader import ScriptError, load_rounds, load_script, validate_references
from .release import assess_release
from .review import (
    SEVERITY_BLOCK,
    SEVERITY_NOTE,
    apply_confirmations,
    knowledge_matrix,
    promise_dossier,
    review_script,
)

DEFAULT_DATA = Path(__file__).resolve().parents[1] / "data" / "records.json"


def _to_plain(value: Any) -> Any:
    if is_dataclass(value):
        return {key: _to_plain(item) for key, item in asdict(value).items()}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): _to_plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_plain(item) for item in value]
    return value


def _emit(payload: Any, as_json: bool) -> None:
    if as_json:
        print(json.dumps(_to_plain(payload), ensure_ascii=False, indent=2))
    else:
        print(_render_text(payload))


def _render_text(payload: Any) -> str:
    if isinstance(payload, dict):
        return "\n".join(f"{key}: {_render_text(value)}" for key, value in payload.items())
    if isinstance(payload, (list, tuple)):
        return "\n".join(_render_text(item) for item in payload)
    if isinstance(payload, Enum):
        return payload.value
    return str(payload)


def _load(paths: Sequence[str]) -> Any:
    if len(paths) == 1:
        return load_script(paths[0])
    return load_rounds(paths)


def cmd_check(args: argparse.Namespace) -> int:
    script = _load(args.files or [str(DEFAULT_DATA)])
    validate_references(script)
    report = review_script(script)
    payload = {
        "source": script.source,
        "scenes": len(script.scenes),
        "edges": len(script.edges),
        "dialogue_lines": len(script.lines),
        "routes_walked": len(report.routes),
        "loops_pruned": len(report.pruned_loops),
        "blocking_findings": sum(item.severity == SEVERITY_BLOCK for item in report.findings),
        "open_questions": len(report.questions),
        "notes": sum(item.severity == SEVERITY_NOTE for item in report.findings),
    }
    _emit(payload, args.json)
    return 0


def cmd_walk(args: argparse.Namespace) -> int:
    script = _load(args.files or [str(DEFAULT_DATA)])
    result = walk(script, args.entry)
    payload = {
        "routes": [
            {
                "route_id": route.route_id,
                "choice_sequence": list(route.edges),
                "scenes": list(route.scenes),
                "end_scene": route.end_scene,
                "terminal": route.terminal,
                "key_holder": route.state.key_holder,
                "played_lines": list(route.state.line_events),
            }
            for route in result.routes
        ],
        "pruned_loops": result.pruned,
    }
    _emit(payload, args.json)
    return 0


def cmd_trace(args: argparse.Namespace) -> int:
    script = _load(args.files or [str(DEFAULT_DATA)])
    choices: dict[tuple, str] = {}
    if args.variant:
        for assignment in args.variant:
            head, line_id = assignment.rsplit(":", 1)
            scene, line_no = head.split(":")
            line_no = int(line_no)
            if "@" in line_id:
                line_id, visit_text = line_id.split("@", 1)
                key: tuple = (scene, line_no, int(visit_text))
            else:
                key = (scene, line_no)
            choices[key] = line_id
    report = trace(script, args.edges, args.entry, choices)
    payload = {
        "entry": report.entry,
        "blocked_edge": report.blocked_edge,
        "reason": report.reason,
        "steps": [
            {
                "index": step.index,
                "edge": step.edge.id if step.edge else None,
                "trigger_satisfied": step.trigger.satisfied if step.trigger else None,
                "trigger_evidence": list(step.trigger.evidence) if step.trigger else [],
                "scene": step.scene,
                "lines_played": list(step.lines_played),
                "key_holder": step.state.key_holder,
            }
            for step in report.steps
        ],
        "promise": promise_dossier(script, report.steps[-1].state),
    }
    _emit(payload, args.json)
    return 0 if report.blocked_edge is None else 2


def cmd_review(args: argparse.Namespace) -> int:
    script = _load(args.files or [str(DEFAULT_DATA)])
    report = review_script(script, entry=args.entry)
    if args.confirmations:
        confirmations = json.loads(Path(args.confirmations).read_text(encoding="utf-8"))
        report = apply_confirmations(report, confirmations)
    payload = {
        "findings": [_to_plain(item) for item in report.findings],
        "compatibility": [_to_plain(item) for item in report.compatibilities],
        "pruned_loops": list(report.pruned_loops),
    }
    _emit(payload, args.json)
    return 1 if any(item.severity == SEVERITY_BLOCK for item in report.findings) else 0


def cmd_knowledge(args: argparse.Namespace) -> int:
    script = _load(args.files or [str(DEFAULT_DATA)])
    report = trace(script, args.edges, args.entry)
    matrix = knowledge_matrix(script, report.steps[-1].state)
    _emit(
        {
            "blocked_edge": report.blocked_edge,
            "knowledge": matrix,
            "promise": promise_dossier(script, report.steps[-1].state),
        },
        args.json,
    )
    return 0


def cmd_release(args: argparse.Namespace) -> int:
    script = _load(args.files or [str(DEFAULT_DATA)])
    review = review_script(script)
    payload: dict[str, Any] = {}
    for release in script.releases:
        if args.plan and release.id not in args.plan:
            continue
        report = assess_release(script, release, review)
        payload[release.id] = _to_plain(report)
    _emit(payload, args.json)
    return 0


def cmd_questions(args: argparse.Namespace) -> int:
    script = _load(args.files or [str(DEFAULT_DATA)])
    report = review_script(script)
    unique: dict[str, dict[str, str]] = {}
    for finding in report.questions:
        if finding.confirm_key and finding.confirm_key not in unique:
            unique[finding.confirm_key] = {
                "scene": finding.scene,
                "edge": finding.edge_id or "",
                "line": finding.line_id or "",
                "question": finding.message,
                "choices": list(finding.choice_sequence),
            }
    if args.write:
        Path(args.write).write_text(
            json.dumps({key: "accepted" for key in unique}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    _emit(unique, args.json)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="drama", description="互动短剧依据追踪与交片评估")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_files(target: argparse.ArgumentParser) -> None:
        target.add_argument(
            "-f",
            "--files",
            nargs="+",
            default=[str(DEFAULT_DATA)],
            help="一轮或多轮 JSON 稿（多份按轮次顺序合并）",
        )

    check_parser = sub.add_parser("check", help="字段/引用自检并汇总审查计数")
    add_files(check_parser)
    check_parser.set_defaults(func=cmd_check)

    walk_parser = sub.add_parser("walk", help="遍历全部分支，列出路线与剪枝")
    add_files(walk_parser)
    walk_parser.add_argument("--entry")
    walk_parser.set_defaults(func=cmd_walk)

    trace_parser = sub.add_parser("trace", help="按实际选择顺序追踪依据断点")
    add_files(trace_parser)
    trace_parser.add_argument("edges", nargs="+", help="边 id 顺序，如 E2 E4 E6")
    trace_parser.add_argument("--entry")
    trace_parser.add_argument(
        "--variant",
        action="append",
        default=[],
        help="变体选择 场景:line_no:台词id，可加 @到访次序 如 S2:2:L10@2",
    )
    trace_parser.set_defaults(func=cmd_trace)

    review_parser = sub.add_parser("review", help="依据审查与共用场景兼容性")
    add_files(review_parser)
    review_parser.add_argument("--entry")
    review_parser.add_argument("--confirmations", help="编剧确认 JSON 文件")
    review_parser.set_defaults(func=cmd_review)

    knowledge_parser = sub.add_parser(
        "knowledge", help="查看某选择顺序下各角色知道的事实与依据"
    )
    add_files(knowledge_parser)
    knowledge_parser.add_argument("edges", nargs="+")
    knowledge_parser.add_argument("--entry")
    knowledge_parser.set_defaults(func=cmd_knowledge)

    release_parser = sub.add_parser("release", help="按片单评估可交付性与按钮一致性")
    add_files(release_parser)
    release_parser.add_argument("--plan", nargs="+", help="只评估指定 release id")
    release_parser.set_defaults(func=cmd_release)

    questions_parser = sub.add_parser(
        "questions", help="导出待编剧确认的问题（含上下文签名键）"
    )
    add_files(questions_parser)
    questions_parser.add_argument("--write", help="把确认单骨架写入文件")
    questions_parser.set_defaults(func=cmd_questions)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except ScriptError as exc:
        print(f"资料错误：{exc}", file=sys.stderr)
        return 3
    except KeyError as exc:
        print(f"确认无效：{exc}", file=sys.stderr)
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
