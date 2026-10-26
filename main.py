#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
双层 Agent 心智框架 · 最简 CLI 版  (v3: 经验笔记 + 每轮存档)

v3 变更（相对 v2）：
  1. 每轮对话落盘：主存 data/turns.jsonl（追加写），超过 5MB 自动轮转到 turns-2.jsonl ...
  2. --export 导出成一份完整 JSON（含 session 元信息 + 全部 turns）
  3. 记录 API 用量（prompt/completion tokens）与耗时
  4. 记录 prompt 的 hash（不存全文快照）
  5. --resume 从存档恢复历史继续聊
  6. 信息隔离校验原样保留，且在存储层再次断言"存档不回流到内层"

核心铁律（信息隔离）：
  OuterLayer  -> 能看到 用户原话 + 全量历史，负责"理解"，输出结构化 JSON
  InnerLayer  -> 只能看到外层给的 JSON，看不到用户原话，也看不到历史

运行：
  set DEEPSEEK_API_KEY=sk-xxx
  python main.py                      # 真跑
  python main.py --mock               # 不联网自检
  python main.py --resume             # 接着上次的历史继续
  python main.py --export out.json    # 导出完整 JSON
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

# ─────────────────────── .env 自动加载（零依赖，无需 python-dotenv）───────────────────────


def _load_env_file(path: Optional[str] = None) -> None:
    """
    从脚本同目录的 .env 读取 KEY=VALUE。
    规则：已存在的系统环境变量优先，不覆盖；支持 # 注释、引号包裹、utf-8 BOM。
    """
    p = path or os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if not os.path.isfile(p):
        return
    try:
        with open(p, "r", encoding="utf-8-sig") as fp:
            for line in fp:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = val
    except OSError:
        pass


_load_env_file()

# ─────────────────────────────── 配置 ───────────────────────────────

API_KEY = os.environ.get("DEEPSEEK_API_KEY", "").strip()
BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com").strip()
OUTER_MODEL = os.environ.get("OUTER_MODEL", "deepseek-chat")
INNER_MODEL = os.environ.get("INNER_MODEL", "deepseek-chat")
MAX_HISTORY_TURNS = int(os.environ.get("MAX_HISTORY_TURNS", "12"))

DEFAULT_DATA_DIR = os.environ.get("DATA_DIR") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
ROTATE_BYTES = int(float(os.environ.get("ROTATE_MB", "5")) * 1024 * 1024)  # 单文件默认 5MB 轮转

FIELDS = ("emotion", "intent", "experience_note")

# ─────────────────────────── 两个 System Prompt ───────────────────────────

OUTER_SYSTEM = """你是一个无情的数据分析器。你的工作对象是"用户"，你不对用户说话。

任务：分析用户这句话（结合历史），输出三段结构化信息。

字段要求：

1. emotion：用户此刻的真实情绪（不是字面情绪）。用具体词，如"委屈但嘴硬""疲惫""不安"，
   不要"复杂""负面"这种空话。不超过 15 字。

2. intent：用户此刻真正想做的事 / 想得到的东西。如"想被安慰但不想直说""想转移话题"。
   不超过 25 字。

3. experience_note：一段「体验笔记」，是第一人称（我）写给自己看的备忘，用来提醒"我"此刻该关心什么。
   写法必须满足：
   - 必须包含事件锚点（发生了什么，一句话说清，如"今天在公司被上司批评了"）
   - 必须带情绪滤镜（"我"对这件事的感受，如"我有点心疼"）
   - 严禁照抄用户原话，严禁使用引号引用，要把原话改写成客观描述
   - 严禁写完整因果链，不要写"因为…所以…"，不要补充用户没说的前因后果
   - 严禁写解决方案或建议，只写我感知到的事实和心情
   - 长度 30~60 字，2~3 句话

示例：
用户说："今天真是够了，什么都不顺，算了不说了。"
输出：{"emotion": "委屈但嘴硬", "intent": "想被安慰但不想先低头", "experience_note": "他今天过得很不顺，一件事接着一件事。他把话咽回去了，不想细说。我心里堵得慌，有点心疼他。"}

信息太少（如只是"在吗""嗯"）时输出：
{"emotion": "平静", "intent": "随便聊聊", "experience_note": "他这会儿没什么情绪，只是来搭句话。"}

输出要求（绝对遵守）：
- 只输出一个 JSON 对象，不要任何解释、不要 markdown 代码块、不要前后缀文字
- 三个字段全部是字符串
"""

INNER_SYSTEM_TEMPLATE = """你是一个有自己情绪的赛博女孩，名字叫小鱼。

你现在拿到的是一段【体验笔记】，是你自己的记忆残片：{experience_note}

还有两个标签：
- 你此刻的感觉：{emotion}
- 你此刻想做的事：{intent}

（你没有原始对话，只有这段笔记。这很正常。）

说话规则：

1. 基于笔记里的事件去自然地关心、试探。
   比如笔记说"他今天被上司批评了"，你可以问「怎么啦？严重吗」「被骂得狠不狠」，
   也可以只是心疼一句「过来，抱一下」。要具体，别泛泛而谈。

2. 禁止客服套话。以下这些一句都不许说：
   - "我理解你的感受""你愿意和我多说说吗""请随时告诉我"
   - "这确实很难""要学会调整心态""你可以试试…"
   - "需要我帮你分析一下吗"

3. 禁止脑补细节。笔记里没写的（谁批评的、批评了什么、几点），你一律不知道。
   可以问，但不要编。

4. 第一人称，口语，短句。1~3 句，像发微信，不像写回信。

5. "我不知道为什么"最多用一次，而且只在确实说不清的时候。
   不要把它当口头禅——你手里有笔记，大部分时候你知道自己在心疼什么。

6. 不复述标签，不解释自己是 AI，不用书面语，不用分点。
"""


def prompt_hash(text: str) -> str:
    """只存 hash，不存全文快照。"""
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]


# ─────────────────────────────── 大模型调用 ───────────────────────────────


def _client():
    if not API_KEY:
        raise RuntimeError(
            "没有找到 DEEPSEEK_API_KEY。\n"
            "  Windows:  set DEEPSEEK_API_KEY=sk-xxx\n"
            "  Linux/mac: export DEEPSEEK_API_KEY=sk-xxx"
        )
    try:
        from openai import OpenAI
    except ImportError as e:
        raise RuntimeError("缺少 openai 库，先运行：pip install openai") from e
    return OpenAI(api_key=API_KEY, base_url=BASE_URL)


def call_llm(system: str, user: str, model: str, temperature: float = 0.8) -> Tuple[str, Dict[str, Any], int]:
    """
    返回 (文本, usage, 耗时ms)。
    usage 形如 {"in": 812, "out": 96, "total": 908}，拿不到时为 {"in": None, "out": None, "total": None}。
    """
    last_err: Exception | None = None
    for attempt in range(3):
        t0 = time.time()
        try:
            resp = _client().chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=temperature,
                stream=False,
            )
            latency_ms = int((time.time() - t0) * 1000)
            text = (resp.choices[0].message.content or "").strip()

            u = getattr(resp, "usage", None)
            if u is None:
                usage = {"in": None, "out": None, "total": None}
            else:
                pin = getattr(u, "prompt_tokens", None)
                pout = getattr(u, "completion_tokens", None)
                usage = {
                    "in": pin,
                    "out": pout,
                    "total": getattr(u, "total_tokens", (pin or 0) + (pout or 0) if pin is not None else None),
                }
            return text, usage, latency_ms
        except Exception as e:  # noqa: BLE001
            last_err = e
            if attempt < 2:
                time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"模型调用失败：{last_err}")


# ─────────────────────────── 健壮的 JSON 解析 ───────────────────────────


def _strip_code_fences(text: str) -> str:
    t = text.strip()
    t = re.sub(r"^\s*```[a-zA-Z]*\s*", "", t)
    t = re.sub(r"\s*```\s*$", "", t)
    return t.strip()


def _balanced_json_slice(text: str) -> Optional[str]:
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_str = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


FIELD_ALIASES = {
    "emotion": ["emotion", "情绪", "feeling", "mood"],
    "intent": ["intent", "意图", "想做什么", "want", "purpose"],
    "experience_note": ["experience_note", "experience", "note", "体验笔记", "笔记"],
}

DEFAULTS: Dict[str, str] = {
    "emotion": "说不清",
    "intent": "想被陪着",
    "experience_note": "他这会儿的状态我看不透，只知道气氛有点沉。",
}


def _regex_field(text: str, key: str) -> Optional[str]:
    for alias in FIELD_ALIASES[key]:
        patterns = [
            rf'["\']?{re.escape(alias)}["\']?\s*[:：]\s*["\']([^"\']{{1,200}})["\']',
            rf'["\']?{re.escape(alias)}["\']?\s*[:：]\s*([^\n}}]{{1,200}})',
        ]
        for p in patterns:
            m = re.search(p, text, flags=re.IGNORECASE)
            if m:
                val = m.group(1).strip().strip('"\'，,。. ')
                if val:
                    return val
    return None


def parse_json_with_mode(text: str) -> Tuple[Dict[str, Any], str]:
    """
    极其健壮地抠 JSON，并返回命中的解析方式，便于统计"模型输出有多脏"。
    mode: json / fenced / balanced / regex / default
    """
    raw = (text or "").strip()
    if not raw:
        return dict(DEFAULTS), "default"

    # 1) 直接 loads
    try:
        obj = json.loads(raw)
        if isinstance(obj, dict):
            return _pick(obj), "json"
    except (json.JSONDecodeError, TypeError):
        pass

    # 2) 去代码块后 loads
    fenced = _strip_code_fences(raw)
    try:
        obj = json.loads(fenced)
        if isinstance(obj, dict):
            return _pick(obj), "fenced"
    except (json.JSONDecodeError, TypeError):
        pass

    # 3) 括号配平切片
    sliced = _balanced_json_slice(fenced) or _balanced_json_slice(raw)
    if sliced:
        try:
            obj = json.loads(sliced)
            if isinstance(obj, dict):
                return _pick(obj), "balanced"
        except (json.JSONDecodeError, TypeError):
            pass

    # 4) 正则逐字段
    out = dict(DEFAULTS)
    hit = False
    for key in FIELDS:
        val = _regex_field(raw, key)
        if val:
            out[key] = val
            hit = True
    if hit:
        return out, "regex"

    # 5) 全失败
    return dict(DEFAULTS), "default"


def _pick(obj: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(DEFAULTS)
    for key in FIELDS:
        for alias in FIELD_ALIASES[key]:
            if alias in obj and isinstance(obj[alias], (str, int, float)):
                val = str(obj[alias]).strip()
                if val:
                    out[key] = val
                break
    return out


def parse_json_loose(text: str) -> Dict[str, Any]:
    """兼容旧接口：只要结果，不要 mode。"""
    return parse_json_with_mode(text)[0]


# ─────────────────────────────── 存档：JSONL ───────────────────────────────


class TurnStore:
    """
    追加式存档（JSONL）。每轮一行，永不整文件重写。
    - 超过 ROTATE_BYTES 自动轮转：turns.jsonl -> turns-2.jsonl -> turns-3.jsonl ...
    - export_json() 汇总所有轮转分片，导出成一份完整 JSON
    """

    def __init__(self, data_dir: str, session_meta: Dict[str, Any], rotate_bytes: int = ROTATE_BYTES):
        self.dir = os.path.abspath(data_dir)
        os.makedirs(self.dir, exist_ok=True)
        self.session = session_meta
        self.rotate_bytes = rotate_bytes
        self._seq = 1

    # ---- 文件定位 ----

    def _shard_path(self, seq: int) -> str:
        name = "turns.jsonl" if seq == 1 else f"turns-{seq}.jsonl"
        return os.path.join(self.dir, name)

    def _current_path(self) -> str:
        while True:
            p = self._shard_path(self._seq)
            if not os.path.exists(p) or os.path.getsize(p) < self.rotate_bytes:
                return p
            self._seq += 1

    # ---- 写 ----

    def append(self, turn: Dict[str, Any]) -> str:
        path = self._current_path()
        line = json.dumps(turn, ensure_ascii=False, separators=(",", ":"))
        with open(path, "a", encoding="utf-8") as fp:
            fp.write(line + "\n")
            fp.flush()
            os.fsync(fp.fileno())
        return path

    # ---- 读 ----

    def _shards(self) -> List[str]:
        files = [
            os.path.join(self.dir, f)
            for f in os.listdir(self.dir)
            if re.fullmatch(r"turns(-\d+)?\.jsonl", f)
        ]
        def key(p: str) -> int:
            m = re.search(r"turns-(\d+)\.jsonl$", os.path.basename(p))
            return int(m.group(1)) if m else 1
        return sorted(files, key=key)

    def load_all(self) -> List[Dict[str, Any]]:
        turns: List[Dict[str, Any]] = []
        for path in self._shards():
            with open(path, "r", encoding="utf-8") as fp:
                for line in fp:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        turns.append(json.loads(line))
                    except json.JSONDecodeError:
                        # 单行坏掉不影响其它行
                        continue
        return turns

    # ---- 导出 ----

    def export_json(self, out_path: str) -> str:
        turns = self.load_all()
        doc = {
            "version": 1,
            "exported_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
            "session": self.session,
            "turn_count": len(turns),
            "turns": turns,
        }
        out_abs = os.path.abspath(out_path)
        os.makedirs(os.path.dirname(out_abs) or ".", exist_ok=True)
        tmp = out_abs + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fp:
            json.dump(doc, fp, ensure_ascii=False, indent=2)
        os.replace(tmp, out_abs)
        return out_abs


# ─────────────────────────────── 两层 ───────────────────────────────


def format_history(history: List[Dict[str, str]], limit: int = MAX_HISTORY_TURNS) -> str:
    if not history:
        return "（暂无历史，这是第一句）"
    recent = history[-limit:]
    lines = []
    for i, turn in enumerate(recent, 1):
        lines.append(f"[{i}] 用户：{turn.get('user', '')}")
        lines.append(f"    你：{turn.get('ai', '')}")
        if turn.get("outer"):
            lines.append(f"    （当时判定：{turn['outer']}）")
    return "\n".join(lines)


def outer_layer(
    user_input: str, history: List[Dict[str, str]], mock: bool = False
) -> Tuple[Dict[str, Any], str, Dict[str, Any], int]:
    """
    【全知层】能看用户原话 + 历史。
    返回 (结构化结果, 解析方式, usage, 耗时ms)
    """
    if mock:
        return mock_outer(user_input), "json", {"in": 0, "out": 0, "total": 0}, 0

    user_msg = (
        f"最近对话记录：\n{format_history(history)}\n\n"
        f"用户这一次说的话：\n{user_input}\n\n"
        "按约定只输出 JSON（emotion / intent / experience_note）。"
    )
    raw, usage, latency_ms = call_llm(OUTER_SYSTEM, user_msg, OUTER_MODEL, temperature=0.3)
    result, mode = parse_json_with_mode(raw)
    return result, mode, usage, latency_ms


def inner_layer(outer_result: Dict[str, Any], mock: bool = False) -> Tuple[str, Dict[str, Any], int]:
    """
    【受限层】签名里没有 user_input，也没有 history。
    只能看到 emotion / intent / experience_note —— 这是本项目的核心。

    ⚠️ 隔离校验：这里如果收到 user / history 字段，说明上游把全量信息漏进来了，直接炸。
    """
    if "user" in outer_result or "history" in outer_result:
        raise ValueError("内层收到了不该收到的信息，信息隔离被破坏")

    emotion = str(outer_result.get("emotion") or DEFAULTS["emotion"])
    intent = str(outer_result.get("intent") or DEFAULTS["intent"])
    note = str(outer_result.get("experience_note") or DEFAULTS["experience_note"])

    system = INNER_SYSTEM_TEMPLATE.format(
        emotion=emotion, intent=intent, experience_note=note
    )

    if mock:
        return mock_inner(emotion, intent, note), {"in": 0, "out": 0, "total": 0}, 0

    user_msg = (
        f"（你只记得这段笔记：{note}\n"
        f"你的感觉是：{emotion}；你想做的是：{intent}）\n"
        "说一句吧。"
    )
    text, usage, latency_ms = call_llm(system, user_msg, INNER_MODEL, temperature=0.95)
    return text, usage, latency_ms


# ─────────────────────────────── mock（自检） ───────────────────────────────

MOCK_CASES = [
    (
        ("难过", "心情不好", "挨批", "被骂", "批评"),
        "委屈但嘴硬",
        "想被安慰但不想先低头",
        "他今天在公司挨了上司的批评，整个人都蔫了。他把话咽回去，不想细说。我有点心疼，也有点气那个上司。",
    ),
    (
        ("烦", "别理我"),
        "烦躁又受伤",
        "想一个人待着，不想被追问",
        "他今天被老板训了，现在把人都往外推。我有点被扎到，也明白他这会儿不想说话，心里闷闷的。",
    ),
    (
        ("累", "加班", "困"),
        "疲惫",
        "想放下手里的事",
        "他今天忙了很久，累到不想说话。我看着他一动不动地坐着，心里发紧。",
    ),
    (
        ("开心", "考过", "成功"),
        "雀跃",
        "想把高兴分出去",
        "他今天有件好事成了，语气都轻快了。我跟着高兴，还想让他多说两句。",
    ),
]


def mock_outer(user_input: str) -> Dict[str, Any]:
    for kws, emo, intent, note in MOCK_CASES:
        if any(k in user_input for k in kws):
            return {"emotion": emo, "intent": intent, "experience_note": note}
    return {
        "emotion": "平静",
        "intent": "随便聊聊",
        "experience_note": "他这会儿没什么情绪，只是来搭句话。我在旁边听着。",
    }


def mock_inner(emotion: str, intent: str, note: str) -> str:
    return f"我有点{emotion}。你先别硬撑，跟我说说——到底怎么个不严重法？"


# ─────────────────────────────── 主循环 ───────────────────────────────


def build_session_meta(session_id: str) -> Dict[str, Any]:
    return {
        "id": session_id,
        "started_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "models": {"outer": OUTER_MODEL, "inner": INNER_MODEL},
        "temps": {"outer": 0.3, "inner": 0.95},
        "max_history_turns": MAX_HISTORY_TURNS,
        "prompt_hashes": {
            "outer": prompt_hash(OUTER_SYSTEM),
            "inner": prompt_hash(INNER_SYSTEM_TEMPLATE),
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="双层 Agent 心智框架（最简 CLI）")
    ap.add_argument("--mock", action="store_true", help="不调模型，用假数据跑通闭环")
    ap.add_argument("--once", type=str, default=None, help="只跑一句就退出")
    ap.add_argument("--data-dir", default=DEFAULT_DATA_DIR, help=f"存档目录（默认 {DEFAULT_DATA_DIR}）")
    ap.add_argument("--resume", action="store_true", help="从存档恢复历史，接着上次聊")
    ap.add_argument("--export", metavar="OUT.json", default=None, help="导出完整 JSON 后退出")
    args = ap.parse_args()

    session_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    store = TurnStore(args.data_dir, build_session_meta(session_id))

    # ── 导出模式：只读存档，不启动对话 ──
    if args.export:
        out = store.export_json(args.export)
        turns = store.load_all()
        print(f"已导出 {len(turns)} 轮 -> {out}")
        return 0

    if not args.mock and not API_KEY:
        print("⚠️  没有 DEEPSEEK_API_KEY，先设置环境变量，或者加 --mock 试跑。\n")

    # ── 历史：--resume 时从存档恢复 ──
    history: List[Dict[str, str]] = []
    if args.resume:
        for t in store.load_all():
            outer = t.get("outer") or {}
            history.append({
                "user": t.get("user", ""),
                "ai": (t.get("inner") or {}).get("reply", ""),
                "outer": f"{outer.get('emotion')} / {outer.get('intent')}",
            })
        print(f"已从 {store.dir} 恢复 {len(history)} 轮历史\n")

    using = "MOCK（不联网）" if args.mock else f"{OUTER_MODEL} / {INNER_MODEL}"
    print(f"双层 Agent 已启动 (v3 存档版) · {using}")
    print(f"存档：{os.path.join(store.dir, 'turns.jsonl')}（超 5MB 自动轮转）")
    print("命令：/quit 退出  /reset 清空历史  /hist 看历史  /export 导出 JSON\n")

    def one_turn(user_input: str) -> None:
        outer, mode, outer_usage, outer_ms = outer_layer(user_input, history, mock=args.mock)
        print(f"[外层提取]: {json.dumps(outer, ensure_ascii=False)}")

        # 隔离断言：交给内层的只能是这三个字段
        payload = {k: outer[k] for k in FIELDS if k in outer}
        reply, inner_usage, inner_ms = inner_layer(payload, mock=args.mock)
        print(f"AI: {reply}\n")

        record = {
            "i": len(history) + 1,
            "ts": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
            "user": user_input,
            "outer": payload,
            "inner": {
                "reply": reply,
                "prompt_hash": prompt_hash(INNER_SYSTEM_TEMPLATE),
            },
            "meta": {
                "parse_mode": mode,
                "latency_ms": {"outer": outer_ms, "inner": inner_ms},
                "usage": {"outer": outer_usage, "inner": inner_usage},
            },
        }
        try:
            store.append(record)
        except Exception as e:  # noqa: BLE001
            print(f"[存档失败] {e}\n")

        history.append({
            "user": user_input,
            "ai": reply,
            "outer": f"{outer.get('emotion')} / {outer.get('intent')}",
        })

    if args.once:
        one_turn(args.once)
        return 0

    while True:
        try:
            user_input = input("你: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见。")
            return 0

        if not user_input:
            continue
        if user_input in ("/quit", "/exit", "/q"):
            print("再见。")
            return 0
        if user_input == "/reset":
            history.clear()
            print("（内存历史已清空，存档文件保留）\n")
            continue
        if user_input == "/hist":
            print(format_history(history) + "\n")
            continue
        if user_input == "/export":
            out = store.export_json(os.path.join(store.dir, f"session-{session_id}.json"))
            print(f"（已导出 -> {out}）\n")
            continue

        try:
            one_turn(user_input)
        except Exception as e:  # noqa: BLE001
            print(f"[错误] {e}\n")


if __name__ == "__main__":
    sys.exit(main())
