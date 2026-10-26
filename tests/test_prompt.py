# -*- coding: utf-8 -*-
"""Prompt 硬约束的回归测试：防止以后改 prompt 时把防幻觉规则删掉。"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import main  # noqa: E402


def test_inner_forbids_physical_body():
    p = main.INNER_SYSTEM_TEMPLATE
    assert "你没有物理身体" in p
    assert "绝对禁止虚构对方的物理动作" in p
    # 反面词要出现在 prompt 里作为禁止示例
    for word in ("关门", "摔东西"):
        assert word in p, f"缺少反例：{word}"


def test_inner_handles_rejecting_short_input():
    p = main.INNER_SYSTEM_TEMPLATE
    assert "带拒绝意味" in p or "极短" in p
    assert "emotion" in p


def test_inner_forbids_fabricating_facts():
    p = main.INNER_SYSTEM_TEMPLATE
    assert "严禁为了接话而编造事实" in p
    assert "用情绪表达代替推测" in p


def test_inner_keeps_isolation_rule():
    """隔离规则不能被误删：内层仍只接受三个字段。"""
    assert "emotion" in main.INNER_SYSTEM_TEMPLATE
    assert "experience_note" in main.INNER_SYSTEM_TEMPLATE
    # 内层 prompt 不该出现"用户原话"这种引导
    assert "用户原话" not in main.INNER_SYSTEM_TEMPLATE


def test_metaphor_boundary_defined():
    """比喻允许描述心理边界，不允许描述物理动作。"""
    p = main.INNER_SYSTEM_TEMPLATE
    assert "比喻的边界" in p
    assert "心门" in p
    assert "摔门" in p


def test_outer_scores_memory_weight():
    """外层必须给记忆打分（1.0~5.0），且写清三档标准。"""
    p = main.OUTER_SYSTEM
    assert "memory_weight" in p
    assert "1.0 ~ 5.0" in p or "1.0~5.0" in p
    assert "5.0" in p and "3.0" in p and "1.0" in p
    assert "永不遗忘" in p


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
