"""读取并校验 JSON 轮次稿，支持把不同轮次的对话稿与分支图合并。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Sequence

from .model import Edge, Line, Release, Role, Scene, Script, Track

TABLES = ("roles", "scenes", "edges", "dialogue", "tracks", "releases")
FIELDS: dict[str, tuple[str, ...]] = {
    "roles": ("id", "name", "aliases"),
    "scenes": ("id", "place", "narration"),
    "edges": ("id", "origin", "target", "option", "trigger"),
    "dialogue": ("id", "scene", "line_no", "speaker", "listeners", "variant", "quote"),
    "tracks": ("id", "line", "language", "ready"),
    "releases": ("id", "entry", "languages", "rights", "options"),
}


class ScriptError(ValueError):
    """资料缺字段、引用悬空或轮次合并冲突。"""


def load_json(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:  # 不信任的外部稿：保留定位信息
        raise ScriptError(f"{source} 不是合法 JSON：{exc}") from exc
    if not isinstance(data, dict):
        raise ScriptError(f"{source} 顶层必须是对象")
    return data


def load_script(path: str | Path, *, label: str | None = None) -> Script:
    data = load_json(path)
    source = str(path)
    script = _build_script(data, source=source, label=label or source)
    validate_references(script)
    return script


def load_rounds(paths: Iterable[str | Path]) -> Script:
    """按轮次顺序读入多份稿并合并。

    后一轮可以新增记录、替换同 id 的台词/边（改口与改图），
    但角色与场景的同 id 记录必须保持一致，冲突直接报错而不是静默覆盖。
    """

    rounds: list[dict[str, Any]] = []
    labels: list[str] = []
    for path in paths:
        source = str(path)
        rounds.append(load_json(source))
        labels.append(source)
    merged = _merge_rounds(rounds, labels)
    script = _build_script(merged, source=" + ".join(labels), label="merged")
    validate_references(script)
    return script


def _merge_rounds(
    rounds: Sequence[dict[str, Any]], labels: Sequence[str]
) -> dict[str, Any]:
    merged: dict[str, list[dict[str, Any]]] = {table: [] for table in TABLES}
    seen: dict[str, dict[str, str]] = {table: {} for table in TABLES}

    for data, label in zip(rounds, labels):
        missing = set(TABLES) - set(data)
        unknown = set(data) - set(TABLES)
        if missing or unknown:
            detail = ", ".join(sorted(missing | unknown))
            raise ScriptError(f"{label} 表结构不符，问题表：{detail}")
        for table in TABLES:
            for row in data[table]:
                row_id = row.get("id")
                if row_id is None:
                    raise ScriptError(f"{label} 的 {table} 存在无 id 记录")
                previous_label = seen[table].get(row_id)
                if previous_label is None:
                    merged[table].append(dict(row))
                    seen[table][row_id] = label
                elif table in ("roles", "scenes"):
                    # 身份表只允许原样重申
                    old = next(item for item in merged[table] if item["id"] == row_id)
                    if old != row:
                        raise ScriptError(
                            f"{table}:{row_id} 在 {previous_label} 与 {label} 中内容冲突"
                        )
                else:
                    # 可变表允许后一轮改口/改图，整行替换并保留原话可追溯需求由轮次稿自身负责
                    for index, item in enumerate(merged[table]):
                        if item["id"] == row_id:
                            merged[table][index] = dict(row)
                            break
    return merged


def _build_script(
    data: dict[str, Any], *, source: str, label: str
) -> Script:
    unknown_tables = set(data) - set(TABLES)
    missing_tables = set(TABLES) - set(data)
    if unknown_tables or missing_tables:
        raise ScriptError(
            f"{label} 表结构不符，多出 {sorted(unknown_tables)}，缺 {sorted(missing_tables)}"
        )

    roles: list[Role] = []
    for row in data["roles"]:
        _check_fields(row, FIELDS["roles"], "roles", label)
        aliases = row["aliases"]
        if not isinstance(aliases, list) or not all(isinstance(a, str) for a in aliases):
            raise ScriptError(f"{label} roles:{row['id']} aliases 必须是字符串数组")
        roles.append(Role(row["id"], row["name"], tuple(aliases)))

    scenes = [
        Scene(row["id"], row["place"], row["narration"])
        for row in data["scenes"]
        if _check_fields(row, FIELDS["scenes"], "scenes", label) or True
    ]

    edges = [
        Edge(row["id"], row["origin"], row["target"], row["option"], row["trigger"])
        for row in data["edges"]
        if _check_fields(row, FIELDS["edges"], "edges", label) or True
    ]

    lines: list[Line] = []
    for row in data["dialogue"]:
        _check_fields(row, FIELDS["dialogue"], "dialogue", label)
        listeners = row["listeners"]
        if not isinstance(listeners, list) or not all(
            isinstance(x, str) for x in listeners
        ):
            raise ScriptError(f"{label} dialogue:{row['id']} listeners 必须是字符串数组")
        if not isinstance(row["line_no"], int):
            raise ScriptError(f"{label} dialogue:{row['id']} line_no 必须是整数")
        lines.append(
            Line(
                row["id"],
                row["scene"],
                row["line_no"],
                row["speaker"],
                tuple(listeners),
                row["variant"],
                row["quote"],
            )
        )

    tracks: list[Track] = []
    for row in data["tracks"]:
        _check_fields(row, FIELDS["tracks"], "tracks", label)
        if not isinstance(row["ready"], bool):
            raise ScriptError(f"{label} tracks:{row['id']} ready 必须是布尔值")
        tracks.append(Track(row["id"], row["line"], row["language"], row["ready"]))

    releases: list[Release] = []
    for row in data["releases"]:
        _check_fields(row, FIELDS["releases"], "releases", label)
        for field_name in ("languages", "rights", "options"):
            if not isinstance(row[field_name], list) or not all(
                isinstance(x, str) for x in row[field_name]
            ):
                raise ScriptError(
                    f"{label} releases:{row['id']} {field_name} 必须是字符串数组"
                )
        releases.append(
            Release(
                row["id"],
                row["entry"],
                tuple(row["languages"]),
                tuple(row["rights"]),
                tuple(row["options"]),
            )
        )

    _unique_ids(roles, "roles", label)
    _unique_ids(scenes, "scenes", label)
    _unique_ids(edges, "edges", label)
    _unique_ids(lines, "dialogue", label)
    _unique_ids(tracks, "tracks", label)
    _unique_ids(releases, "releases", label)

    # 同场景同 line_no 下 variant 不得重复，默认稿至多一条
    variant_seen: set[tuple[str, int, str]] = set()
    for line in lines:
        marker = (line.scene, line.line_no, line.variant)
        if marker in variant_seen:
            raise ScriptError(
                f"{label} dialogue:{line.id} 的 (scene,line_no,variant) 重复：{marker}"
            )
        variant_seen.add(marker)

    origins = {row_id: label for table in TABLES for row_id in (r["id"] for r in data[table])}
    return Script(
        tuple(roles),
        tuple(scenes),
        tuple(edges),
        tuple(lines),
        tuple(tracks),
        tuple(releases),
        source=source,
        origins=origins,
    )


def _check_fields(
    row: dict[str, Any], expected: tuple[str, ...], table: str, label: str
) -> bool:
    if set(row) != set(expected):
        raise ScriptError(
            f"{label} {table}:{row.get('id', '?')} 字段应为 {set(expected)}，实际 {set(row)}"
        )
    return False


def _unique_ids(rows: Sequence[Any], table: str, label: str) -> None:
    ids = [row.id for row in rows]
    if len(ids) != len(set(ids)):
        duplicates = sorted({value for value in ids if ids.count(value) > 1})
        raise ScriptError(f"{label} {table} 存在重复 id：{duplicates}")


def validate_references(script: Script) -> None:
    """交叉引用完整性；悬空引用一律报错。"""

    role_ids = {role.id for role in script.roles}
    scene_ids = {scene.id for scene in script.scenes}
    line_ids = {line.id for line in script.lines}
    edge_ids = {edge.id for edge in script.edges}

    def check(value: str | Sequence[str], allowed: set[str], where: str) -> None:
        values = value if isinstance(value, (list, tuple)) else [value]
        dangling = [item for item in values if item not in allowed]
        if dangling:
            raise ScriptError(f"{where} 引用了不存在的记录：{dangling}")

    for edge in script.edges:
        check(edge.origin, scene_ids, f"edges:{edge.id}.origin")
        check(edge.target, scene_ids, f"edges:{edge.id}.target")
    for line in script.lines:
        check(line.scene, scene_ids, f"dialogue:{line.id}.scene")
        check(line.speaker, role_ids, f"dialogue:{line.id}.speaker")
        check(line.listeners, role_ids, f"dialogue:{line.id}.listeners")
    for track in script.tracks:
        check(track.line, line_ids, f"tracks:{track.id}.line")
    for release in script.releases:
        check(release.entry, scene_ids, f"releases:{release.id}.entry")
        check(release.options, edge_ids, f"releases:{release.id}.options")
        # languages 是计划制作语言，rights 是实际授权语言；允许 languages 超出
        # rights（未授权语言在交片评估中自然不可交付），反向则说明授权登记有误。
        unauthorized = set(release.rights) - set(release.languages)
        if unauthorized:
            raise ScriptError(
                f"releases:{release.id} 授权 rights {sorted(unauthorized)} "
                "不在计划 languages 内"
            )
