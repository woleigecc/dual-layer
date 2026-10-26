# -*- coding: utf-8 -*-
"""记忆归属与越权拦截的测试。

可以直接跑：
    python tests/test_memory.py
也兼容 pytest：
    pytest tests/test_memory.py -q
"""

import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import main  # noqa: E402
from memory import InnerMemoryStore, PermissionError_  # noqa: E402


def _fresh_store():
    tmp = tempfile.mkdtemp(prefix="mem-test-")
    return InnerMemoryStore(os.path.join(tmp, "memory.json"))


# ───────────────────────── 核心：内层没有访问权 ─────────────────────────


def test_inner_cannot_touch_memory():
    """内层持有记忆引用，但任何查询都必须抛越权异常。"""
    store = _fresh_store()
    store.write_memory("他把那句话咽回去了，我心里堵得慌。", anchor="他在公司被批")

    inner = main.InnerLayer(store.as_inner_handle("inner-小鱼"), mock=True)

    # 引用确实在她手上（归属）
    assert inner.inner_memory_store is not None

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

    # 封条上的东西也没被写进去
    assert all("偷写" not in e["text"] for e in store.entries())


def test_outer_can_read_and_write():
    store = _fresh_store()
    outer = main.OuterLayer(store, mock=True)
    outer.inner_memory_store.write_memory("他说被领导批了，我听着有点心疼。", anchor="被领导批")
    assert len(outer.inner_memory_store.entries()) == 1
    assert outer.memory_stats()["count"] == 1


# ───────────────────────── 写入路径：她表达愿望，外层代执行 ─────────────────────────


def test_wish_marker_detected_and_removed():
    raw = "你今天怎么啦，被批得狠不狠？\n[我想记住：他今天被领导批了，说得很轻，我心里堵。]"
    clean, wishes = main.split_wishes(raw)
    assert clean == "你今天怎么啦，被批得狠不狠？"
    assert len(wishes) == 1
    assert wishes[0].startswith("他今天被领导批了")


def test_outer_commits_inner_wish():
    """完整链路：内层产出带标记的回复 → 外层解析并写盘 → 正文里没有标记。"""
    store = _fresh_store()
    outer = main.OuterLayer(store, mock=True)
    inner = main.InnerLayer(store.as_inner_handle(), mock=True)

    payload = {
        "emotion": "心跳加快",
        "intent": "想把这一刻留下来",
        "experience_note": "他忽然说了句我想记住的话。",
    }
    raw_reply, _usage, _ms = inner.reply(payload)
    assert "[我想记住：" in raw_reply  # mock 内层会带标记

    clean, written = outer.commit_wishes(raw_reply, anchor=payload["experience_note"])
    assert "[我想记住" not in clean
    assert len(written) == 1
    assert len(store.entries()) == 1

    entry = store.entries()[0]
    assert entry["source"] == "inner_wish"
    assert entry["text"] == written[0]["text"]
    assert entry["anchor"] == payload["experience_note"]


def test_duplicate_wish_not_stored_twice():
    store = _fresh_store()
    outer = main.OuterLayer(store, mock=True)
    reply = "嗯。\n[我想记住：今天他说的那句话我记下了。]"
    outer.commit_wishes(reply, anchor="")
    outer.commit_wishes(reply, anchor="")
    assert len(store.entries()) == 1


# ───────────────────────── 读取路径：最近 + 关键词 ─────────────────────────


def test_recall_prefers_relevant():
    store = _fresh_store()
    store.write_memory("他说工作上的事，我记着加班。", anchor="工作加班")
    store.write_memory("他喜欢喝冰美式，不加糖。", anchor="喝咖啡")
    store.write_memory("他养了只猫叫团团。", anchor="养猫")

    got = store.recall("今天又加班了", k=2)
    assert got, "应该至少回忆起一条"
    assert any("加班" in e["text"] for e in got)


def test_recall_empty_when_no_memory():
    store = _fresh_store()
    assert store.recall("随便") == []


# ───────────────────────── 端到端：mock 一轮 ─────────────────────────


def test_end_to_end_mock_turn():
    store = _fresh_store()
    outer = main.OuterLayer(store, mock=True)
    inner = main.InnerLayer(store.as_inner_handle(), mock=True)

    outer_result, mode, _u, _ms = outer.analyze("记住这天，他今天被领导批了", [])
    payload = {k: outer_result[k] for k in main.FIELDS if k in outer_result}
    raw, _u2, _ms2 = inner.reply(payload)
    clean, written = outer.commit_wishes(raw, anchor=payload.get("experience_note", ""))

    assert mode == "json"
    assert clean and "[我想记住" not in clean
    assert written, "mock 场景下应该写进一条记忆"
    assert len(store.entries()) == 1


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
