# -*- coding: utf-8 -*-
"""内层的海马体 v2：带权重的记忆新陈代谢。

哲学不变：记忆归内层（她的经历），访问权在外层（潜意识解锁器）。
工程新增：
- 每条记忆带 weight（1.0~5.0）与 last_accessed
- 被想起 -> 权重 +0.1（上限 5.0），模拟"越回忆越深刻"
- 超过容量 -> 按权重/时间淘汰最弱的，但 weight>=4.5 的永不删
"""

from __future__ import annotations

import json
import os
import tempfile
import time
import uuid
from typing import Any, Dict, List, Optional

DEFAULT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "memory.json")

MAX_ENTRIES = 50          # 触发清理的容量上限
PROTECTED_WEIGHT = 4.5    # 达到这个权重永不自动删除
RECALL_MIN_WEIGHT = 1.5   # 低于这个权重不参与回忆
REWARD_STEP = 0.1         # 每被想起一次 +0.1
MAX_WEIGHT = 5.0
DEFAULT_WEIGHT = 3.0


class PermissionError_(Exception):
    """内层越权访问记忆时抛出。"""


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def _parse_iso(s: str) -> float:
    """把 ISO 时间戳转成可比较的浮点；解析失败返回 0（视为最旧）。"""
    if not s:
        return 0.0
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return time.mktime(time.strptime(s, fmt))
        except ValueError:
            continue
    return 0.0


def _clamp_weight(w: Any) -> float:
    try:
        v = float(w)
    except (TypeError, ValueError):
        return DEFAULT_WEIGHT
    return max(1.0, min(MAX_WEIGHT, round(v, 2)))


class FrozenMemoryHandle:
    """内层的「记忆引用」——只有归属，没有权限。"""

    __slots__ = ("_owner", "_path")

    def __init__(self, owner: str, path: str):
        object.__setattr__(self, "_owner", owner)
        object.__setattr__(self, "_path", path)

    def read_memory(self, *a, **k):
        raise PermissionError_(
            "内层的记忆属于你，但此刻没有访问权：read_memory() 只能由外层（潜意识解锁器）调用"
        )

    def write_memory(self, *a, **k):
        raise PermissionError_(
            "内层的记忆属于你，但此刻没有访问权：write_memory() 只能由外层（潜意识解锁器）调用"
        )

    def recall(self, *a, **k):
        raise PermissionError_("回忆是被代理调度的：recall() 只能由外层调用")

    def entries(self, *a, **k):
        raise PermissionError_("记忆条目对你是不可见的：entries() 只能由外层调用")

    def stats(self, *a, **k):
        raise PermissionError_("记忆统计对你是不可见的")

    def __getattr__(self, name: str):
        raise PermissionError_(f"内层不得访问记忆接口：{name!r}")

    def __repr__(self) -> str:
        return f"<FrozenMemoryHandle owner={self._owner!r} path={self._path!r} 无访问权>"


class InnerMemoryStore:
    """记忆真身（v2：带权重）。**只允许 OuterLayer 持有并调度。**"""

    def __init__(self, path: Optional[str] = None, capacity: int = MAX_ENTRIES):
        self.path = os.path.abspath(path or DEFAULT_PATH)
        self.capacity = capacity
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        if not os.path.exists(self.path):
            self._save({"version": 2, "entries": []})

    # ── 底层 IO ──

    def _load_raw(self) -> Dict[str, Any]:
        try:
            with open(self.path, "r", encoding="utf-8") as fp:
                data = json.load(fp)
            if not isinstance(data, dict) or "entries" not in data:
                raise ValueError("bad shape")
            return data
        except (OSError, json.JSONDecodeError, ValueError):
            return {"version": 2, "entries": []}

    def _save(self, data: Dict[str, Any]) -> None:
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(self.path), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fp:
                json.dump(data, fp, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
        finally:
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass

    # ── 迁移：v1(text/ts/anchor) -> v2(content/timestamp/weight/last_accessed) ──

    def _migrate(self, entry: Dict[str, Any]) -> Dict[str, Any]:
        if "content" in entry:
            out = dict(entry)
        else:
            ts = entry.get("ts") or entry.get("date") or _now_iso()
            out = {
                "id": entry.get("id") or uuid.uuid4().hex[:12],
                "content": entry.get("text") or "",
                "timestamp": ts,
                "weight": _clamp_weight(entry.get("weight", DEFAULT_WEIGHT)),
                "last_accessed": entry.get("last_accessed") or ts,
            }
            if entry.get("anchor"):
                out["anchor"] = entry["anchor"]
            out["source"] = entry.get("source", "legacy_v1")
        out["weight"] = _clamp_weight(out.get("weight", DEFAULT_WEIGHT))
        out.setdefault("last_accessed", out.get("timestamp", _now_iso()))
        out.setdefault("timestamp", out.get("last_accessed", _now_iso()))
        out.setdefault("id", uuid.uuid4().hex[:12])
        return out

    def entries(self) -> List[Dict[str, Any]]:
        raw = self._load_raw()
        return [self._migrate(e) for e in raw.get("entries", [])]

    def read_memory(self) -> List[Dict[str, Any]]:
        return self.entries()

    # ── 写入 ──

    def write_memory(
        self,
        content: str,
        anchor: str = "",
        source: str = "inner_wish",
        weight: float = DEFAULT_WEIGHT,
    ) -> Optional[Dict[str, Any]]:
        content = (content or "").strip()
        if not content:
            return None
        all_entries = self.entries()
        # 去重：同一句话不重复记（权重取较高者）
        for e in all_entries:
            if e.get("content") == content:
                e["weight"] = max(e["weight"], _clamp_weight(weight))
                e["last_accessed"] = _now_iso()
                self._save({"version": 2, "entries": all_entries})
                return e

        now = _now_iso()
        entry = {
            "id": uuid.uuid4().hex[:12],
            "content": content,
            "timestamp": now,
            "weight": _clamp_weight(weight),
            "last_accessed": now,
            "source": source,
        }
        if anchor:
            entry["anchor"] = anchor.strip()[:160]
        all_entries.append(entry)
        all_entries = self._evict(all_entries)
        self._save({"version": 2, "entries": all_entries})
        return entry

    # ── 淘汰 ──

    def _evict(self, entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """超过容量时按「权重最低 + 最久没想起」淘汰，weight>=4.5 永不删。"""
        if len(entries) <= self.capacity:
            return entries

        def sort_key(e: Dict[str, Any]):
            return (e.get("weight", DEFAULT_WEIGHT), _parse_iso(e.get("last_accessed", "")))

        ordered = sorted(entries, key=sort_key)  # 弱的在前
        keep = []
        removed = 0
        need = len(entries) - self.capacity
        for e in ordered:
            if removed < need and e.get("weight", DEFAULT_WEIGHT) < PROTECTED_WEIGHT:
                removed += 1
                continue
            keep.append(e)
        # 受保护条目太多、删不够时保持原样（宁可超一点，也不删核心记忆）
        return keep

    # ── 回忆（含权重奖励）──

    def recall(self, query: str = "", k: int = 5, reward: bool = True) -> List[Dict[str, Any]]:
        """
        过滤 weight < 1.5，按 weight 降序 + last_accessed 降序取前 k 条。
        被取出的记忆：last_accessed = now，weight += 0.1（上限 5.0）。
        """
        all_entries = self.entries()
        candidates = [e for e in all_entries if e.get("weight", 0) >= RECALL_MIN_WEIGHT]
        if not candidates:
            return []

        candidates.sort(
            key=lambda e: (e.get("weight", 0), _parse_iso(e.get("last_accessed", ""))),
            reverse=True,
        )
        picked = candidates[: max(int(k), 0)]

        if reward and picked:
            now = _now_iso()
            for e in picked:
                e["last_accessed"] = now
                e["weight"] = _clamp_weight(min(MAX_WEIGHT, e.get("weight", 0) + REWARD_STEP))
            self._save({"version": 2, "entries": all_entries})

        return picked

    # ── 统计 ──

    def stats(self) -> Dict[str, Any]:
        entries = self.entries()
        if not entries:
            return {"count": 0, "avg_weight": 0.0, "max_weight": 0.0, "top": [], "path": self.path}
        weights = [e.get("weight", DEFAULT_WEIGHT) for e in entries]
        top = sorted(entries, key=lambda e: e.get("weight", 0), reverse=True)[:3]
        return {
            "count": len(entries),
            "avg_weight": round(sum(weights) / len(weights), 2),
            "max_weight": max(weights),
            "capacity": self.capacity,
            "top": [
                {"weight": e.get("weight"), "content": e.get("content"), "when": e.get("timestamp")}
                for e in top
            ],
            "path": self.path,
        }

    # ── 给内层的封条 ──

    def as_inner_handle(self, owner: str = "inner") -> FrozenMemoryHandle:
        return FrozenMemoryHandle(owner=owner, path=self.path)


def format_recall(entries: List[Dict[str, Any]]) -> str:
    """把回忆条目拼成给外层看的文本（带权重，便于它判断分量）。"""
    if not entries:
        return ""
    lines = []
    for e in entries:
        w = e.get("weight", DEFAULT_WEIGHT)
        when = (e.get("timestamp") or "")[:10]
        anchor = f"（{e['anchor']}）" if e.get("anchor") else ""
        lines.append(f"- [{w:.1f}] {when} {e.get('content', '')}{anchor}")
    return "\n".join(lines)
