# -*- coding: utf-8 -*-
"""记忆归属、权重打分、回忆奖励与淘汰的测试。

跑法：
    python tests/test_memory.py
也兼容 pytest：
    pytest tests/test_memory.py -q
"""

import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import main  # noqa: E402
from memory import InnerMemoryStore, PermissionError_  # noqa: E402
from memory.store import MAX_ENTRIES, RECALL_MIN_WEIGHT  # noqa: E402


def _fresh_store(capacity=MAX_ENTRIES):
    tmp = tempfile.mkdtemp(prefix="mem-test-")
    return InnerMemoryStore(os.path.join(tmp, "memory.json"), capacity=capacity)


# ───────────────────── 核心：内层没有访问权 ─────────────────────


def test_inner_cannot_touch_memory():
    """内层持有记忆引用，但任何查询都必须抛越权异常。"""
    store = _fresh_store()
    store.write_memory("他把那句话咽回去了，我心里堵得慌。", anchor="他在公司被批", weight=4.0)

    inner = main.InnerLayer(store.as_inner_handle("inner-小鱼"), mock=True)
    assert inner.inner_memory_store is not None  # 引用在手上（归属）

    checks = [
        lambda: inner.inner_memory_store.read_memory(),
        lambda: inner.inner_memory_store.write_memory("偷写一条"),
        lambda: inner.inner_memory_store.recall("随便"),
        lambda: inner.inner_memory_store.entries(),
        lambda: inner.inner_memory_store.stats(),
    ]
    for fn in checks:
        try:
            fn()
        except PermissionError_:
            continue
        raise AssertionError("内层居然成功访问了记忆接口，隔离被破坏")

    assert all("偷写" not in e["content"] for e in store.entries())


def test_outer_can_read_and_write():
    store = _fresh_store()
    outer = main.OuterLayer(store, mock=True)
    outer.inner_memory_store.write_memory("他说被领导批了，我听着有点心疼。", anchor="被领导批", weight=3.5)
    entries = outer.inner_memory_store.entries()
    assert len(entries) == 1
    assert entries[0]["weight"] == 3.5
    assert outer.memory_stats()["count"] == 1


# ───────────────────── 写入：她表达愿望，外层打分执行 ─────────────────────


def test_wish_marker_detected_and_removed():
    raw = "你今天怎么啦，被批得狠不狠？\n[我想记住：他今天被领导批了，说得很轻，我心里堵。]"
    clean, wishes = main.split_wishes(raw)
    assert clean == "你今天怎么啦，被批得狠不狠？"
    assert len(wishes) == 1
    assert wishes[0].startswith("他今天被领导批了")


def test_outer_commits_inner_wish_with_weight():
    """完整链路：内层产出带标记的回复 → 外层带权重写盘 → 正文里没有标记。"""
    store = _fresh_store()
    outer = main.OuterLayer(store, mock=True)
    inner = main.InnerLayer(store.as_inner_handle(), mock=True)

    payload = {
        "emotion": "心跳加快",
        "intent": "想把这一刻留下来",
        "experience_note": "他忽然说了句我想记住的话。",
    }
    raw_reply, _u, _ms = inner.reply(payload)
    assert "[我想记住：" in raw_reply  # mock 内层会带标记

    clean, written = outer.commit_wishes(raw_reply, anchor=payload["experience_note"], weight=4.6)
    assert "[我想记住" not in clean
    assert len(written) == 1
    assert written[0]["weight"] == 4.6

    entry = store.entries()[0]
    assert entry["source"] == "inner_wish"
    assert entry["content"] == written[0]["content"]
    assert entry["anchor"] == payload["experience_note"]


def test_duplicate_wish_takes_higher_weight():
    store = _fresh_store()
    outer = main.OuterLayer(store, mock=True)
    reply = "嗯。\n[我想记住：今天他说的那句话我记下了。]"
    outer.commit_wishes(reply, weight=2.0)
    outer.commit_wishes(reply, weight=4.8)
    entries = store.entries()
    assert len(entries) == 1, "同一句话不该记两条"
    assert entries[0]["weight"] == 4.8, "重复写入应取较高权重"


# ───────────────────── 回忆：过滤 / 排序 / 权重奖励 ─────────────────────


def test_recall_filters_low_weight():
    store = _fresh_store()
    store.write_memory("今天中午吃了面。", weight=1.0)   # 低于阈值
    store.write_memory("他加班到很晚，我有点担心。", weight=3.0)
    picked = store.recall(k=5)
    assert len(picked) == 1
    assert "加班" in picked[0]["content"]
    assert all(e["weight"] >= RECALL_MIN_WEIGHT for e in picked)


def test_recall_orders_by_weight_then_access():
    store = _fresh_store()
    store.write_memory("低权重的记忆", weight=2.0)
    store.write_memory("高权重的记忆", weight=4.5)
    picked = store.recall(k=5)
    assert picked[0]["content"] == "高权重的记忆"


def test_recall_rewards_weight():
    """被想起一次：权重 +0.1，last_accessed 更新。"""
    store = _fresh_store()
    store.write_memory("他今天说很崩溃。", weight=4.0)
    first = store.recall(k=1)[0]
    assert first["weight"] == 4.1
    second = store.recall(k=1)[0]
    assert second["weight"] == 4.2
    # 落盘也生效
    assert store.entries()[0]["weight"] == 4.2


def test_recall_reward_capped_at_five():
    store = _fresh_store()
    store.write_memory("核心记忆", weight=4.95)
    store.recall(k=1)
    store.recall(k=1)
    assert store.entries()[0]["weight"] == 5.0, "权重不能超过 5.0"


def test_recall_empty_when_no_memory():
    assert _fresh_store().recall("随便") == []


# ───────────────────── 淘汰：超容量时删最弱，核心记忆不删 ─────────────────────


def test_eviction_drops_lowest_weight():
    store = _fresh_store(capacity=3)
    store.write_memory("弱1", weight=1.6)
    store.write_memory("弱2", weight=2.0)
    store.write_memory("强1", weight=4.0)
    store.write_memory("新来的", weight=3.0)  # 触发淘汰
    contents = [e["content"] for e in store.entries()]
    assert len(contents) == 3
    assert "弱1" not in contents, "应淘汰权重最低的那条"


def test_eviction_never_deletes_core_memory():
    store = _fresh_store(capacity=2)
    store.write_memory("核心记忆A", weight=4.8)
    store.write_memory("核心记忆B", weight=5.0)
    store.write_memory("日常1", weight=2.0)
    store.write_memory("日常2", weight=1.8)
    contents = [e["content"] for e in store.entries()]
    assert "核心记忆A" in contents
    assert "核心记忆B" in contents, "weight>=4.5 永不删除"


# ───────────────────── 迁移：v1 老格式能读 ─────────────────────


def test_migration_from_v1():
    tmp = tempfile.mkdtemp(prefix="mem-mig-")
    path = os.path.join(tmp, "memory.json")
    with open(path, "w", encoding="utf-8") as fp:
        json.dump(
            {"version": 1, "entries": [
                {"id": "m1", "ts": "2026-10-26T18:00:00+0800", "text": "旧格式的一条记忆",
                 "anchor": "旧锚点", "source": "inner_wish"}
            ]},
            fp,
            ensure_ascii=False,
        )
    store = InnerMemoryStore(path)
    entries = store.entries()
    assert len(entries) == 1
    e = entries[0]
    assert e["content"] == "旧格式的一条记忆"
    assert e["weight"] == 3.0
    assert e["timestamp"].startswith("2026-10-26")


# ───────────────────── 统计 ─────────────────────


def test_stats_shape():
    store = _fresh_store()
    store.write_memory("a", weight=2.0)
    store.write_memory("b", weight=4.0)
    s = store.stats()
    assert s["count"] == 2
    assert s["avg_weight"] == 3.0
    assert s["max_weight"] == 4.0
    assert len(s["top"]) == 2
    assert s["top"][0]["content"] == "b"


# ───────────────────── 端到端 ─────────────────────


def test_end_to_end_mock_turn():
    store = _fresh_store()
    outer = main.OuterLayer(store, mock=True)
    inner = main.InnerLayer(store.as_inner_handle(), mock=True)

    outer_result, mode, _u, _ms = outer.analyze("记住这天，他今天被领导批了", [])
    payload = {k: outer_result[k] for k in main.FIELDS if k in outer_result}
    raw, _u2, _ms2 = inner.reply(payload)
    clean, written = outer.commit_wishes(
        raw, anchor=payload.get("experience_note", ""),
        weight=float(outer_result.get("memory_weight", main.DEFAULT_MEMORY_WEIGHT)),
    )

    assert mode == "json"
    assert clean and "[我想记住" not in clean
    assert written, "mock 场景下应该写进一条记忆"
    assert store.entries()[0]["weight"] == 4.5  # mock_outer 对"记住"类给的权重


def _run_all():
    funcs = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in funcs:
        try:
            fn()
            print(f"[PASS] {fn.__name__}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"[FAIL] {fn.__name__}: {e}")
    print(f"\n{len(funcs) - failed}/{len(funcs)} 通过")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(_run_all())
