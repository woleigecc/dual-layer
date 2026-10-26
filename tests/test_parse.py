# -*- coding: utf-8 -*-
"""测试 parse_json_loose 的健壮性。"""
import sys

sys.path.insert(0, r'C:\Users\cao13\Documents\deepseek-harness\default-workspace\dual-layer')
import main  # noqa: E402

cases = {
    '干净 JSON': '{"emotion": "委屈", "intent": "想被安慰", "experience_note": "他今天被批评了，我心疼。"}',
    '带代码块': '```json\n{"emotion": "委屈", "intent": "想被安慰", "experience_note": "他今天被批评了，我心疼。"}\n```',
    '前后有废话': '好的，分析如下：\n{"emotion": "疲惫", "intent": "想躺平", "experience_note": "他忙了一天，累坏了。"}\n希望有帮助！',
    '只有裸键值': 'emotion: 委屈\nintent: 想被安慰\nexperience_note: 他今天被批评了，我心疼。',
    '字符串里有花括号': '{"emotion": "复杂{累}", "intent": "想躺平", "experience_note": "他说了句{a}然后沉默了。"}',
    '完全跑偏': '我觉得他今天不太好，但说不清楚。',
    '空输出': '',
}

for name, raw in cases.items():
    out = main.parse_json_loose(raw)
    print(f'[{name}]')
    print(f'  emotion={out["emotion"]!r}')
    print(f'  intent={out["intent"]!r}')
    print(f'  note={out["experience_note"]!r}')
