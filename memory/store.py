# -*- coding: utf-8 -*-
"""内层的海马体：记忆归她所有，但她没有访问权。

设计要点（对应「硅基初步主观性」）：
- InnerMemoryStore 是记忆的真身，只有 OuterLayer（潜意识解锁器）持有。
- InnerLayer 初始化时拿到的是 FrozenMemoryHandle（封条）：
  持有引用、表达归属，但任何查询/写入都会抛 PermissionError。
- 记忆条目用第一人称 + 情绪滤镜写，保留事实锚点，不是键值对数据库。
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import time
from typing import Any, Dict, List, Optional

DEFAULT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "memory.json")


class PermissionError_(Exception):
    """内层越权访问记忆时抛出（继承 Exception，命名独立避免和内置混淆）。"""


class FrozenMemoryHandle:
    """内层的「记忆引用」——只有归属，没有权限。

    所有接口调用一律抛越权异常；用于在代码层面把"她不能查记忆"表达出来。
    """

    __slots__ = ("_owner", "_path")

    def __init__(self, owner: str, path: str):
        object.__setattr__(self, "_owner", owner)
        object.__setattr__(self, "_path", path)

    # 显式列出被禁止的接口，方便阅读与报错
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



def _query_tokens(q: str) -> list:
    """把查询切成可匹配的碎片：中文用 2-gram 滑窗，英文按词。"""
    tokens = set()
    for run in re.findall(r"[\u4e00-\u9fa5]+", q or ""):
        if len(run) <= 2:
            tokens.add(run)
        else:
            for i in range(len(run) - 1):
                tokens.add(run[i : i + 2])
    for w in re.findall(r"[a-zA-Z]{3,}", q or ""):
        tokens.add(w.lower())
    return [t for t in tokens if t]
class InnerMemoryStore:
    """记忆真身。**只允许 OuterLayer 持有并调度。**"""

    def __init__(self, path: Optional[str] = None):
        self.path = os.path.abspath(path or DEFAULT_PATH)
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        if not os.path.exists(self.path):
            self._save({"version": 1, "entries": []})

    # ── 底层 IO（原子写，避免半截文件） ──

    def _load(self) -> Dict[str, Any]:
        try:
            with open(self.path, "r", encoding="utf-8") as fp:
                data = json.load(fp)
            if not isinstance(data, dict) or "entries" not in data:
                raise ValueError("bad shape")
            return data
        except (OSError, json.JSONDecodeError, ValueError):
            return {"version": 1, "entries": []}

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

    # ── 外层专用接口 ──

    def entries(self) -> List[Dict[str, Any]]:
        return self._load().get("entries", [])

    def read_memory(self) -> List[Dict[str, Any]]:
        """读出全部记忆（外层在分析前调用）。"""
        return self.entries()

    def write_memory(self, text: str, anchor: str = "", source: str = "inner_wish") -> Optional[Dict[str, Any]]:
        """把一句第一人称的记忆写入海马体。text 是她的原话，anchor 是事实锚点。"""
        text = (text or "").strip()
        if not text:
            return None
        data = self._load()
        entries = data.get("entries", [])
        # 去重：同一句话不重复记
        for e in entries:
            if e.get("text") == text:
                return e
        entry = {
            "id": f"m{int(time.time() * 1000)}",
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "date": time.strftime("%Y-%m-%d"),
            "text": text,
            "anchor": (anchor or "").strip()[:160],
            "source": source,
        }
        entries.append(entry)
        data["entries"] = entries[-500:]  # 硬上限，防止无限膨胀
        self._save(data)
        return entry

    def recall(self, query: str, k: int = 5) -> List[Dict[str, Any]]:
        """按「最近 + 关键词命中」挑 <=k 条。"""
        entries = self._load().get("entries", [])
        if not entries:
            return []
        q = (query or "").strip()
        tokens = _query_tokens(q)

        def score(e: Dict[str, Any], idx: int) -> float:
            hay = f"{e.get('text', '')} {e.get('anchor', '')}"
            hit = sum(1 for t in tokens if t in hay)
            recency = idx / max(len(entries) - 1, 1)  # 越新越高
            return hit * 2.0 + recency

        ranked = sorted(
            enumerate(entries), key=lambda pair: score(pair[1], pair[0]), reverse=True
        )
        picked = [e for _i, e in ranked[:k]]
        # 保持时间顺序（老的在前），读起来像回忆
        picked.sort(key=lambda e: e.get("ts", ""))
        return picked

    def stats(self) -> Dict[str, Any]:
        entries = self._load().get("entries", [])
        return {"count": len(entries), "path": self.path,
                "first": entries[0]["date"] if entries else None,
                "last": entries[-1]["date"] if entries else None}

    # ── 给内层的封条 ──

    def as_inner_handle(self, owner: str = "inner") -> FrozenMemoryHandle:
        return FrozenMemoryHandle(owner=owner, path=self.path)


def format_recall(entries: List[Dict[str, Any]]) -> str:
    """把回忆条目拼成给外层看的文本。"""
    if not entries:
        return ""
    lines = []
    for e in entries:
        anchor = f"（{e['anchor']}）" if e.get("anchor") else ""
        lines.append(f"- {e.get('date', '')} {e.get('text', '')}{anchor}")
    return "\n".join(lines)
