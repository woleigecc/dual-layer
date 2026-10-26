# -*- coding: utf-8 -*-
"""JSON 解析健壮性测试：脏输出也必须能抠出三个字段，且永不抛异常。

跑法：
    python tests/test_parse.py
也兼容 pytest：
    pytest tests/test_parse.py -q
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import main  # noqa: E402

CASES = {
    "干净 JSON": (
        '{"emotion": "委屈", "intent": "想被安慰", "experience_note": "他今天被批评了，我心疼。"}',
        "json",
    ),
    "带代码块": (
        '```json\n{"emotion": "委屈", "intent": "想被安慰", "experience_note": "他今天被批评了，我心疼。"}\n```',
        "fenced",
    ),
    "前后有废话": (
        '好的，分析如下：\n{"emotion": "疲惫", "intent": "想躺平", "experience_note": "他忙了一天，累坏了。"}\n希望有帮助！',
        "balanced",
    ),
    "只有裸键值": (
        "emotion: 委屈\nintent: 想被安慰\nexperience_note: 他今天被批评了，我心疼。",
        "regex",
    ),
    "字符串里有花括号": (
        '{"emotion": "复杂{累}", "intent": "想躺平", "experience_note": "他说了句{a}然后沉默了。"}',
        "json",
    ),
    "完全跑偏": ("我觉得他今天不太好，但说不清楚。", "default"),
    "空输出": ("", "default"),
    "字段别名": ('{"情绪": "憋屈", "意图": "想被听见", "体验笔记": "他憋着没说。"}', "json"),
    "权重是字符串": (
        '{"emotion": "平静", "intent": "闲聊", "experience_note": "随便聊聊。", "memory_weight": "4.2"}',
        "json",
    ),
}


def test_parse_cases():
    for name, (raw, expected_mode) in CASES.items():
        out, mode = main.parse_json_with_mode(raw)
        assert isinstance(out, dict), f"{name}: 结果不是 dict"
        for key in main.FIELDS:
            assert key in out and isinstance(out[key], str) and out[key], f"{name}: 缺少字段 {key}"
        assert mode == expected_mode, f"{name}: 解析方式应为 {expected_mode}，实际 {mode}"
        # 解析永远不崩、永远有默认值
        assert out["experience_note"].strip()


def test_weight_parsed():
    out = main.parse_json_loose('{"emotion": "x", "intent": "y", "experience_note": "z", "memory_weight": "4.6"}')
    assert out["memory_weight"] == 4.6


def test_weight_clamped():
    out = main.parse_json_loose('{"emotion": "x", "intent": "y", "experience_note": "z", "memory_weight": 99}')
    assert out["memory_weight"] == 5.0


def test_defaults_on_garbage():
    out = main.parse_json_loose("完全不是 JSON 的一段胡话")
    assert out["emotion"] == main.DEFAULTS["emotion"]
    assert out["experience_note"] == main.DEFAULTS["experience_note"]


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
    print(f"\n{len(funcs) - failed}/{len(funcs)} 通过（覆盖 {len(CASES)} 种脏输出）")
    return 1 if failed else 0


if __name__ == "__main__":
    if "--verbose" in sys.argv:
        for name, (raw, _m) in CASES.items():
            out = main.parse_json_loose(raw)
            print(f"[{name}] emotion={out['emotion']!r} note={out['experience_note']!r}")
        print()
    sys.exit(_run_all())
