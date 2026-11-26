"""资料表的不可变数据模型。

只做结构表达与索引，不做任何剧本判断；判断依据分别放在 acts/state/review。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Sequence


@dataclass(frozen=True)
class Role:
    id: str
    name: str
    aliases: tuple[str, ...]

    @property
    def all_terms(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys((self.name, *self.aliases)))


@dataclass(frozen=True)
class Scene:
    id: str
    place: str
    narration: str


@dataclass(frozen=True)
class Edge:
    id: str
    origin: str
    target: str
    option: str
    trigger: str


@dataclass(frozen=True)
class Line:
    """一句登记台词。variant 为空串表示该 line_no 下的默认稿。"""

    id: str
    scene: str
    line_no: int
    speaker: str
    listeners: tuple[str, ...]
    variant: str
    quote: str

    @property
    def key(self) -> tuple[str, int]:
        return (self.scene, self.line_no)

    @property
    def is_variant(self) -> bool:
        return bool(self.variant)


@dataclass(frozen=True)
class Track:
    id: str
    line: str
    language: str
    ready: bool


@dataclass(frozen=True)
class Release:
    id: str
    entry: str
    languages: tuple[str, ...]
    rights: tuple[str, ...]
    options: tuple[str, ...]


@dataclass(frozen=True)
class Script:
    """一轮完整资料；多轮合并结果同样是一个 Script。"""

    roles: tuple[Role, ...]
    scenes: tuple[Scene, ...]
    edges: tuple[Edge, ...]
    lines: tuple[Line, ...]
    tracks: tuple[Track, ...]
    releases: tuple[Release, ...]
    source: str = ""
    # 每条记录来自哪一轮稿，用于编剧追溯
    origins: Mapping[str, str] = field(default_factory=dict)

    def role(self, role_id: str) -> Role:
        return self._roles[role_id]

    def scene(self, scene_id: str) -> Scene:
        return self._scenes[scene_id]

    def edge(self, edge_id: str) -> Edge:
        return self._edges[edge_id]

    def line(self, line_id: str) -> Line:
        return self._lines[line_id]

    def edges_from(self, scene_id: str) -> tuple[Edge, ...]:
        return self._out.get(scene_id, ())

    def lines_at(self, scene_id: str) -> tuple[Line, ...]:
        return self._scene_lines.get(scene_id, ())

    def variant_groups(self) -> dict[tuple[str, int], tuple[Line, ...]]:
        """同场景同 line_no 的候选台词（含默认稿）。"""

        groups: dict[tuple[str, int], list[Line]] = {}
        for line in self.lines:
            groups.setdefault(line.key, []).append(line)
        return {key: tuple(group) for key, group in groups.items()}

    def tracks_for(self, line_id: str) -> tuple[Track, ...]:
        return self._line_tracks.get(line_id, ())

    def __post_init__(self) -> None:
        object.__setattr__(self, "_roles", {r.id: r for r in self.roles})
        object.__setattr__(self, "_scenes", {s.id: s for s in self.scenes})
        object.__setattr__(self, "_edges", {e.id: e for e in self.edges})
        object.__setattr__(self, "_lines", {l.id: l for l in self.lines})
        out: dict[str, list[Edge]] = {}
        for edge in self.edges:
            out.setdefault(edge.origin, []).append(edge)
        object.__setattr__(
            self,
            "_out",
            {scene: tuple(edges) for scene, edges in sorted(out.items())},
        )
        scene_lines: dict[str, list[Line]] = {}
        for line in sorted(self.lines, key=lambda x: (x.line_no, x.variant)):
            scene_lines.setdefault(line.scene, []).append(line)
        object.__setattr__(
            self,
            "_scene_lines",
            {scene: tuple(items) for scene, items in sorted(scene_lines.items())},
        )
        line_tracks: dict[str, list[Track]] = {}
        for track in self.tracks:
            line_tracks.setdefault(track.line, []).append(track)
        object.__setattr__(
            self,
            "_line_tracks",
            {line: tuple(items) for line, items in sorted(line_tracks.items())},
        )

    # dataclass(frozen=True) 下缓存索引
    _roles: Mapping[str, Role] = field(default_factory=dict, repr=False, compare=False)
    _scenes: Mapping[str, Scene] = field(default_factory=dict, repr=False, compare=False)
    _edges: Mapping[str, Edge] = field(default_factory=dict, repr=False, compare=False)
    _lines: Mapping[str, Line] = field(default_factory=dict, repr=False, compare=False)
    _out: Mapping[str, tuple[Edge, ...]] = field(
        default_factory=dict, repr=False, compare=False
    )
    _scene_lines: Mapping[str, tuple[Line, ...]] = field(
        default_factory=dict, repr=False, compare=False
    )
    _line_tracks: Mapping[str, tuple[Track, ...]] = field(
        default_factory=dict, repr=False, compare=False
    )


def role_by_term(script: Script, term: str) -> Role | None:
    """按名字或称呼找角色（处理“他/她大姐”这类引用）。"""

    for role in script.roles:
        if term in role.all_terms:
            return role
    return None


def scene_sequence(script: Script, scene_ids: Sequence[str]) -> tuple[Scene, ...]:
    return tuple(script.scene(sid) for sid in scene_ids)
