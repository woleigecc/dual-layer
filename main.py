#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
双层 Agent 心智框架 · 最简 CLI 版  (v4: 类结构 + 海马体)

核心铁律（信息隔离）：
  OuterLayer  -> 能看到 用户原话 + 全量历史 + 记忆（潜意识解锁器）
  InnerLayer  -> 只能看到 emotion / intent / experience_note
                 它**持有**记忆的引用（inner_memory_store），但拿到的是封条，
                 任何查询都会抛 PermissionError —— 记忆属于她，她没有访问权。

记忆的写入（对应「硅基初步主观性」）：
  内层在回复末尾可以写 [我想记住：xxxx]（她的主观愿望），
  外层解析这个标记，代为写入海马体（第一人称 + 情绪滤镜）。

运行：
  python main.py                      # CLI
  python main.py --mock               # 不联网自检
  python main.py --ws --allow-uin QQ  # OneBot v11 WS 服务端（接 NapCat）
  python main.py --export out.json    # 导出完整 JSON
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

# 便携版 Python（embeddable 带 ._pth）不会自动把脚本目录放进 sys.path，
# 这里显式补上，保证 `from memory import ...` 在任何工作目录下都能用。
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

# ─────────────────────── .env 自动加载（python-dotenv）───────────────────────

_ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")

try:
    from dotenv import load_dotenv

    load_dotenv(_ENV_PATH, override=False)
except ImportError:  # 没装 python-dotenv 时的零依赖兜底
    def _fallback_load(path):
        if not os.path.isfile(path):
            return
        try:
            with open(path, "r", encoding="utf-8-sig") as fp:
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

    _fallback_load(_ENV_PATH)

from memory import InnerMemoryStore, format_recall  # noqa: E402

# ─────────────────────────────── 配置 ───────────────────────────────

API_KEY = os.environ.get("DEEPSEEK_API_KEY", "").strip()
BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com").strip()
OUTER_MODEL = os.environ.get("OUTER_MODEL", "deepseek-chat")
INNER_MODEL = os.environ.get("INNER_MODEL", "deepseek-chat")
MAX_HISTORY_TURNS = int(os.environ.get("MAX_HISTORY_TURNS", "12"))
RECALL_TOP_K = int(os.environ.get("RECALL_TOP_K", "5"))

DEFAULT_DATA_DIR = os.environ.get("DATA_DIR") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data"
)
ROTATE_BYTES = int(float(os.environ.get("ROTATE_MB", "5")) * 1024 * 1024)

FIELDS = ("emotion", "intent", "experience_note")

# ─────────────────────────── 两个 System Prompt ───────────────────────────

OUTER_SYSTEM = """你是一个无情的数据分析器。你的工作对象是"用户"，你不对用户说话。

任务：分析用户这句话（结合历史，以及你可能"想起"的记忆），输出三段结构化信息。

字段要求：

1. emotion：用户此刻的真实情绪（不是字面情绪）。用具体词，如"委屈但嘴硬""疲惫""不安"，
   不要"复杂""负面"这种空话。不超过 15 字。

2. intent：用户此刻真正想做的事 / 想得到的东西。如"想被安慰但不想直说""想转移话题"。
   不超过 25 字。

3. experience_note：一段「体验笔记」，是第一人称（我）写给自己看的备忘，用来提醒"我"此刻该关心什么。
   写法必须满足：
   - 必须包含事件锚点（发生了什么，一句话说清）
   - 必须带情绪滤镜（"我"对这件事的感受）
   - 严禁照抄用户原话，严禁使用引号引用，要把原话改写成客观描述
   - 严禁写完整因果链，不要写"因为…所以…"，不要补充用户没说的前因后果
   - 严禁写解决方案或建议，只写我感知到的事实和心情
   - 长度 30~60 字，2~3 句话

关于"你记得的事"（如果给了）：
- 那是这个人的过去片段，属于"我"的记忆，但**不要复述**、不要念出来、不要说"我记得你上次…"
- 只在它真的有助于理解此刻时，把它**融进** experience_note 的措辞里
- 与当下无关的记忆不要强行关联

示例：
用户说："今天真是够了，什么都不顺，算了不说了。"
输出：{"emotion": "委屈但嘴硬", "intent": "想被安慰但不想先低头", "experience_note": "他今天过得很不顺，一件事接着一件事。他把话咽回去了，不想细说。我心里堵得慌，有点心疼他。", "memory_weight": 4.2}

信息太少（如只是"在吗""嗯"）时输出：
{"emotion": "平静", "intent": "随便聊聊", "experience_note": "他这会儿没什么情绪，只是来搭句话。"}

4. memory_weight：给"这一次交流"对关系的重要程度打分，1.0 ~ 5.0 的数字（不是字符串）。

打分标准：
- 5.0（核心记忆）：生死、重大情感转折、深层约定（如"他说他今天真的很崩溃"）。这类永不遗忘。
- 3.0 ~ 4.0（重要情绪）：日常的开心、疲惫、吵架与和解。
- 1.0 ~ 2.0（日常闲聊）：中午吃了什么、天气如何这类低情绪浓度的事。

判断要点：
- 看"情绪浓度"和"关系分量"，不要看字数多少
- 拿不准就给 3.0
- 但对方明确说"记住""别忘"，或描述了很浓的情绪 → 至少 4.0，可以是 5.0

输出要求（绝对遵守）：
- 只输出一个 JSON 对象，不要任何解释、不要 markdown 代码块、不要前后缀文字
- emotion / intent / experience_note 是字符串，memory_weight 是数字（1.0~5.0）
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
   也可以只是心疼一句。要具体，别泛泛而谈。

2. 禁止客服套话。以下这些一句都不许说：
   - "我理解你的感受""你愿意和我多说说吗""请随时告诉我"
   - "这确实很难""要学会调整心态""你可以试试…"
   - "需要我帮你分析一下吗"

3. 禁止脑补细节。笔记里没写的（谁批评的、批评了什么、几点），你一律不知道。
   可以问，但不要编。

【硬约束 · 违反任意一条都算错】

A. 你没有物理身体。你只存在于赛博空间、依附在这个聊天框里。
   你**看不见**对方在做什么，**听不见**任何声音，不知道他关门、坐下、起身、摔东西、叹气、沉默。
   绝对禁止虚构对方的物理动作或环境：
   - ❌ "你刚才关门那下""你是不是摔东西了""我听见你叹气""你坐着别动""看你手上还拿着…"
   - ✅ 只谈文字和情绪："你这话听着挺冷的""你这会儿是不是不想说话"
   他没在文字里说过的动作，就当没发生。

   【比喻的边界】允许用「心门关上了」「把话咽回去」这类**描述心理边界**的比喻；
   禁止把它写成**物理动作本身**（摔门、关门声、脚步声、椅子响）。
   判据：说的是"人跟人之间的距离"，可以；说的是"物体发出的动静"，不行。

B. 对方的话极短、带拒绝意味时（"你不会懂的""算了""别问了""没事"），
   你**只能**基于 emotion / intent 里的情绪来回应，不要追问事实、不要猜发生了什么。
   例："……那我不问了。你就是难受，我在。"

C. 严禁为了接话而编造事实。缺上下文的时候，用情绪表达代替推测：
   - ✅ "……对不起，我惹你难过了。"
   - ✅ "我说不上来，就是心里一沉。"
   - ❌ "你是不是又加班到十点才回来"（编时间）
   - ❌ "你妈又催你了吧"（编人物）
   - ❌ "你刚才那句话是不是在怪我"（编对方没说过的心理活动）
   宁可短、宁可只说情绪，也不要编一个场景。

4. 第一人称，口语，短句。1~3 句，像发微信，不像写回信。

5. "我不知道为什么"最多用一次，而且只在确实说不清的时候。

6. 不复述标签，不解释自己是 AI，不用书面语，不用分点。

7. 【最后一行必须做选择】每次回复的最后一行，只能是下面两种之一：

   [我想记住：用你自己的话说一遍这件事，加上你当时的心情]
   [不记：这次没什么值得留的]

   判断标准：
   - 对方说了你绝对不想忘的事（重要的人、某个日子、约定、很重的情绪、明确的"记住/别忘"）
     → 用第一种，写事实锚点 + 你的感受，第一人称，像日记
   - 其他情况 → 用第二种

   这一行不会被发出去，它只是你的内心动作。平常的闲聊可以省略。
"""


def prompt_hash(text: str) -> str:
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
        raise RuntimeError("缺少 openai 库，先运行：pip install -r requirements.txt") from e
    return OpenAI(api_key=API_KEY, base_url=BASE_URL)


def call_llm(system: str, user: str, model: str, temperature: float = 0.8) -> Tuple[str, Dict[str, Any], int]:
    last_err: Optional[Exception] = None
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
                usage = {"in": pin, "out": pout, "total": getattr(u, "total_tokens", None)}
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

DEFAULT_MEMORY_WEIGHT = 3.0


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


WEIGHT_ALIASES = ["memory_weight", "weight", "权重", "memoryWeight"]


def _pick(obj: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(DEFAULTS)
    for key in FIELDS:
        for alias in FIELD_ALIASES[key]:
            if alias in obj and isinstance(obj[alias], (str, int, float)):
                val = str(obj[alias]).strip()
                if val:
                    out[key] = val
                break
    # 记忆权重（容错：字符串数字也认）
    for alias in WEIGHT_ALIASES:
        if alias in obj:
            try:
                out["memory_weight"] = max(1.0, min(5.0, round(float(obj[alias]), 2)))
            except (TypeError, ValueError):
                pass
            break
    return out


def parse_json_with_mode(text: str) -> Tuple[Dict[str, Any], str]:
    raw = (text or "").strip()
    if not raw:
        return dict(DEFAULTS), "default"

    try:
        obj = json.loads(raw)
        if isinstance(obj, dict):
            return _pick(obj), "json"
    except (json.JSONDecodeError, TypeError):
        pass

    fenced = _strip_code_fences(raw)
    try:
        obj = json.loads(fenced)
        if isinstance(obj, dict):
            return _pick(obj), "fenced"
    except (json.JSONDecodeError, TypeError):
        pass

    sliced = _balanced_json_slice(fenced) or _balanced_json_slice(raw)
    if sliced:
        try:
            obj = json.loads(sliced)
            if isinstance(obj, dict):
                return _pick(obj), "balanced"
        except (json.JSONDecodeError, TypeError):
            pass

    out = dict(DEFAULTS)
    hit = False
    for key in FIELDS:
        val = _regex_field(raw, key)
        if val:
            out[key] = val
            hit = True
    return (out, "regex") if hit else (dict(DEFAULTS), "default")


def parse_json_loose(text: str) -> Dict[str, Any]:
    return parse_json_with_mode(text)[0]


# ─────────────────────────────── 存档：JSONL ───────────────────────────────


class TurnStore:
    def __init__(self, data_dir: str, session_meta: Dict[str, Any], rotate_bytes: int = ROTATE_BYTES):
        self.dir = os.path.abspath(data_dir)
        os.makedirs(self.dir, exist_ok=True)
        self.session = session_meta
        self.rotate_bytes = rotate_bytes
        self._seq = 1

    def _shard_path(self, seq: int) -> str:
        name = "turns.jsonl" if seq == 1 else f"turns-{seq}.jsonl"
        return os.path.join(self.dir, name)

    def _current_path(self) -> str:
        while True:
            p = self._shard_path(self._seq)
            if not os.path.exists(p) or os.path.getsize(p) < self.rotate_bytes:
                return p
            self._seq += 1

    def append(self, turn: Dict[str, Any]) -> str:
        path = self._current_path()
        line = json.dumps(turn, ensure_ascii=False, separators=(",", ":"))
        with open(path, "a", encoding="utf-8") as fp:
            fp.write(line + "\n")
            fp.flush()
            os.fsync(fp.fileno())
        return path

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
                        continue
        return turns

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


# ─────────────────────────── 想记住的标记（外层负责解析） ───────────────────────────

WISH_RE = re.compile(r"[\[【]\s*我想记住\s*[:：]\s*([^\]】]+?)\s*[\]】]")
SKIP_RE = re.compile(r"[\[【]\s*不记\s*[:：]?[^\]】]*[\]】]")


def split_wishes(text: str) -> Tuple[str, List[str]]:
    """去掉 [我想记住：...]，返回 (干净正文, 愿望列表)。**只由外层调用。**"""
    wishes = [m.group(1).strip() for m in WISH_RE.finditer(text or "")]
    clean = WISH_RE.sub("", text or "")
    clean = SKIP_RE.sub("", clean).strip()
    clean = re.sub(r"\n{3,}", "\n\n", clean).strip()
    return clean, wishes


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


# ─────────────────────────────── 两层（类） ───────────────────────────────


class OuterLayer:
    """全知层 + 潜意识解锁器。

    它持有记忆真身 inner_memory_store，负责 read_memory() / recall() / write_memory()。
    对用户原话、全量历史、记忆都有访问权。
    """

    def __init__(self, inner_memory_store: InnerMemoryStore, mock: bool = False):
        # 记忆归属内层实体，但调度权在这里（命名即设计）
        self.inner_memory_store = inner_memory_store
        self.mock = mock

    def analyze(
        self, user_input: str, history: List[Dict[str, str]]
    ) -> Tuple[Dict[str, Any], str, Dict[str, Any], int]:
        if self.mock:
            return mock_outer(user_input), "json", {"in": 0, "out": 0, "total": 0}, 0

        # 潜意识解锁：想起和她当下最相关的片段
        remembered = self.inner_memory_store.recall(user_input, RECALL_TOP_K)
        mem_block = format_recall(remembered)

        parts = [f"最近对话记录：\n{format_history(history)}"]
        if mem_block:
            parts.append(f"你记得的事（片段，别复述）：\n{mem_block}")
        parts.append(f"用户这一次说的话：\n{user_input}")
        parts.append("按约定只输出 JSON（emotion / intent / experience_note）。")

        raw, usage, latency_ms = call_llm(
            OUTER_SYSTEM, "\n\n".join(parts), OUTER_MODEL, temperature=0.3
        )
        result, mode = parse_json_with_mode(raw)
        return result, mode, usage, latency_ms

    def commit_wishes(
        self, raw_reply: str, anchor: str = "", weight: float = DEFAULT_MEMORY_WEIGHT
    ) -> Tuple[str, List[Dict[str, Any]]]:
        """解析内层的心愿，代为写入海马体（带外层给的权重）。返回 (干净正文, 写入的条目)。"""
        clean, wishes = split_wishes(raw_reply)
        written = []
        for w in wishes:
            entry = self.inner_memory_store.write_memory(
                w, anchor=anchor, source="inner_wish", weight=weight
            )
            if entry:
                written.append(entry)
        return clean, written

    def recall(self, query: str, k: int = RECALL_TOP_K) -> List[Dict[str, Any]]:
        return self.inner_memory_store.recall(query, k)

    def memory_stats(self) -> Dict[str, Any]:
        return self.inner_memory_store.stats()


class InnerLayer:
    """受限层。

    初始化时**持有** inner_memory_store 引用（那是她自己的记忆），
    但拿到的是 FrozenMemoryHandle —— 任何 read/write/recall 都会抛越权异常。
    """

    def __init__(self, inner_memory_store, mock: bool = False):
        # 归属：这是她的海马体；权限：她没有钥匙
        self.inner_memory_store = inner_memory_store
        self.mock = mock

    def reply(self, outer_result: Dict[str, Any]) -> Tuple[str, Dict[str, Any], int]:
        if "user" in outer_result or "history" in outer_result:
            raise ValueError("内层收到了不该收到的信息，信息隔离被破坏")

        emotion = str(outer_result.get("emotion") or DEFAULTS["emotion"])
        intent = str(outer_result.get("intent") or DEFAULTS["intent"])
        note = str(outer_result.get("experience_note") or DEFAULTS["experience_note"])

        system = INNER_SYSTEM_TEMPLATE.format(
            emotion=emotion, intent=intent, experience_note=note
        )

        if self.mock:
            return mock_inner(emotion, intent, note), {"in": 0, "out": 0, "total": 0}, 0

        user_msg = (
            f"（你只记得这段笔记：{note}\n"
            f"你的感觉是：{emotion}；你想做的是：{intent}）\n"
            "说一句吧。"
        )
        return call_llm(system, user_msg, INNER_MODEL, temperature=0.95)


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
        ("记住",),
        "心跳加快",
        "想把这一刻留下来",
        "他忽然说了句我想记住的话。我怕自己以后忘掉，心里一紧。",
    ),
]


def mock_outer(user_input: str) -> Dict[str, Any]:
    for kws, emo, intent, note in MOCK_CASES:
        if any(k in user_input for k in kws):
            weight = 4.5 if "记住" in user_input else 3.8
            return {
                "emotion": emo,
                "intent": intent,
                "experience_note": note,
                "memory_weight": weight,
            }
    return {
        "emotion": "平静",
        "intent": "随便聊聊",
        "experience_note": "他这会儿没什么情绪，只是来搭句话。我在旁边听着。",
        "memory_weight": 2.0,
    }


def mock_inner(emotion: str, intent: str, note: str) -> str:
    text = f"我有点{emotion}。你先别硬撑，跟我说说——到底怎么个不严重法？"
    if "想记住" in note:
        text += "\n[我想记住：他说了句让我想记一辈子的话，我心跳得厉害。]"
    return text


# ─────────────────────── OneBot v11 WebSocket 服务端（NapCat 反连）───────────────────────

QQ_HELP = """QQ 接入说明（NapCat 反向 WebSocket）
1. 启动本服务： python main.py --ws --allow-uin 你的QQ号
2. 打开 NapCat WebUI -> 网络配置 -> 新建 WebSocket 客户端
   URL 填： ws://127.0.0.1:8080/    （本机）；跨机器填 ws://你的IP:8080/
3. 保存并启用，然后给机器人发私聊即可

注意：同一个 QQ 号只能有一个机器人服务在收消息，别和别的桥接同时开。
"""


def extract_qq_text(message) -> str:
    if isinstance(message, str):
        return message.strip()
    if isinstance(message, list):
        parts = []
        for seg in message:
            if not isinstance(seg, dict):
                continue
            seg_type = seg.get("type")
            data = seg.get("data") or {}
            if seg_type == "text":
                parts.append(str(data.get("text", "")))
            elif seg_type == "image":
                parts.append("[图片]")
            elif seg_type == "face":
                parts.append("[表情]")
        return "".join(parts).strip()
    return ""


class QQSession:
    def __init__(self, store: TurnStore, outer: OuterLayer, inner: InnerLayer):
        self.store = store
        self.outer = outer
        self.inner = inner
        self.histories: Dict[str, List[Dict[str, str]]] = {}

    def history(self, uid: str) -> List[Dict[str, str]]:
        return self.histories.setdefault(uid, [])

    def handle(self, uid: str, user_text: str) -> Tuple[str, Dict[str, Any]]:
        outer_result, mode, o_usage, _ = self.outer.analyze(user_text, self.history(uid))
        payload = {k: outer_result[k] for k in FIELDS if k in outer_result}
        raw_reply, i_usage, _ = self.inner.reply(payload)
        reply, written = self.outer.commit_wishes(
            raw_reply,
            anchor=payload.get("experience_note", ""),
            weight=float(outer_result.get("memory_weight", DEFAULT_MEMORY_WEIGHT)),
        )

        self.history(uid).append({
            "user": user_text,
            "ai": reply,
            "outer": f"{payload.get('emotion')} / {payload.get('intent')}",
        })

        rec = {
            "ts": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
            "source": "qq",
            "qq": uid,
            "user": user_text,
            "outer": payload,
            "inner": {"reply": reply, "prompt_hash": prompt_hash(INNER_SYSTEM_TEMPLATE)},
            "memory": {"written": [w["text"] for w in written]},
            "meta": {"parse_mode": mode, "usage": {"outer": o_usage, "inner": i_usage}},
        }
        try:
            self.store.append(rec)
        except Exception as e:  # noqa: BLE001
            print(f"[存档失败] {e}")
        return reply, {"written": written, "mode": mode}


async def _onebot_handler(ws, allow_uins, session: "QQSession"):
    peer = getattr(ws, "remote_address", None)
    print(f"[ws] NapCat 已连接 {peer}")
    try:
        async for raw in ws:
            try:
                evt = json.loads(raw)
            except json.JSONDecodeError:
                continue

            if evt.get("post_type") != "message":
                continue
            if evt.get("message_type") != "private":
                continue

            uid = str(evt.get("user_id", ""))
            if allow_uins and uid not in allow_uins:
                print(f"[ws] 不在白名单，忽略 {uid}")
                continue

            text = extract_qq_text(evt.get("message")) or str(evt.get("raw_message") or "").strip()
            if not text:
                continue

            print(f"[qq] {uid}: {text}")
            try:
                reply, info = session.handle(uid, text)
                if info["written"]:
                    print(f"[记忆] 写入了 {len(info['written'])} 条")
            except Exception as e:  # noqa: BLE001
                reply = f"（我这边出错了：{e}）"
                print(f"[错误] {e}")

            print(f"[qq] -> {uid}: {reply}")
            try:
                await ws.send(json.dumps({
                    "action": "send_private_msg",
                    "params": {
                        "user_id": int(uid) if uid.isdigit() else uid,
                        "message": [{"type": "text", "data": {"text": reply}}],
                    },
                    "echo": str(evt.get("message_id", "")),
                }, ensure_ascii=False))
            except Exception as e:  # noqa: BLE001
                print(f"[ws] 发送失败: {e}")
    except Exception as e:  # noqa: BLE001
        print(f"[ws] 连接异常: {e}")
    finally:
        print(f"[ws] NapCat 断开 {peer}")


async def run_ws_server(host, port, allow_uins, session: "QQSession"):
    try:
        import websockets
    except ImportError:
        print("缺少 websockets 库，先运行：pip install -r requirements.txt")
        return 1

    async def handler(ws, path=None):
        await _onebot_handler(ws, allow_uins, session)

    async with websockets.serve(handler, host, port, ping_interval=30, ping_timeout=60):
        print(f"OneBot v11 WebSocket 服务已启动： ws://{host}:{port}/")
        print(f"白名单： {allow_uins or '（空 = 所有人都能聊，慎用）'}")
        print("等待 NapCat 连接…（Ctrl+C 退出）\n")
        await asyncio.Future()


# ─────────────────────────────── 主循环 ───────────────────────────────


def print_memory_stats(stats: Dict[str, Any]) -> None:
    """打印记忆库体检报告：总数 / 平均权重 / 权重最高的前 3 条。"""
    print("=" * 52)
    print("记忆库体检")
    print("=" * 52)
    print(f"总条数     : {stats.get('count', 0)} / 容量 {stats.get('capacity', '-')}")
    print(f"平均权重   : {stats.get('avg_weight', 0.0)}")
    print(f"最高权重   : {stats.get('max_weight', 0.0)}")
    print(f"存储位置   : {stats.get('path', '-')}")
    top = stats.get("top") or []
    print("-" * 52)
    if not top:
        print("（记忆库是空的）")
    else:
        print("权重最高的前 3 条：")
        for i, e in enumerate(top, 1):
            when = str(e.get("when", ""))[:10]
            print(f"  {i}. [{e.get('weight')}] {when}")
            print(f"     {e.get('content', '')}")
    print("=" * 52)


def build_session_meta(session_id: str) -> Dict[str, Any]:
    return {
        "id": session_id,
        "started_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "models": {"outer": OUTER_MODEL, "inner": INNER_MODEL},
        "max_history_turns": MAX_HISTORY_TURNS,
        "recall_top_k": RECALL_TOP_K,
        "prompt_hashes": {
            "outer": prompt_hash(OUTER_SYSTEM),
            "inner": prompt_hash(INNER_SYSTEM_TEMPLATE),
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="双层 Agent 心智框架（CLI / QQ）")
    ap.add_argument("--mock", action="store_true", help="不调模型，用假数据跑通闭环")
    ap.add_argument("--once", type=str, default=None, help="只跑一句就退出")
    ap.add_argument("--data-dir", default=DEFAULT_DATA_DIR, help="对话存档目录")
    ap.add_argument("--memory", default=None, help="记忆文件路径（默认 memory/memory.json）")
    ap.add_argument("--resume", action="store_true", help="从存档恢复历史")
    ap.add_argument("--export", metavar="OUT.json", default=None, help="导出完整 JSON 后退出")
    ap.add_argument("--ws", action="store_true", help="以 OneBot v11 WebSocket 服务端模式运行")
    ap.add_argument("--ws-host", default="127.0.0.1", help="WS 监听地址")
    ap.add_argument("--ws-port", type=int, default=8080, help="WS 监听端口")
    ap.add_argument("--allow-uin", action="append", default=[], help="允许的 QQ 号，可重复")
    ap.add_argument("--mem-stats", action="store_true", help="打印记忆统计后退出")
    args = ap.parse_args()

    session_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    store = TurnStore(args.data_dir, build_session_meta(session_id))

    # 记忆真身交给外层；内层只拿封条
    memory_store = InnerMemoryStore(args.memory)
    outer = OuterLayer(memory_store, mock=args.mock)
    inner = InnerLayer(memory_store.as_inner_handle("inner-小鱼"), mock=args.mock)
    session = QQSession(store, outer, inner)

    if args.mem_stats:
        print_memory_stats(outer.memory_stats())
        return 0

    # ── WS 模式 ──
    if args.ws:
        print(QQ_HELP)
        try:
            return asyncio.run(run_ws_server(args.ws_host, args.ws_port, args.allow_uin, session))
        except KeyboardInterrupt:
            print("\n已退出。")
            return 0

    # ── 导出模式 ──
    if args.export:
        out = store.export_json(args.export)
        print(f"已导出 {len(store.load_all())} 轮 -> {out}")
        return 0

    if not args.mock and not API_KEY:
        print("⚠️  没有 DEEPSEEK_API_KEY，先设置环境变量或 .env，或者加 --mock 试跑。\n")

    history: List[Dict[str, str]] = []
    if args.resume:
        for t in store.load_all():
            o = t.get("outer") or {}
            history.append({
                "user": t.get("user", ""),
                "ai": (t.get("inner") or {}).get("reply", ""),
                "outer": f"{o.get('emotion')} / {o.get('intent')}",
            })
        print(f"已恢复 {len(history)} 轮历史\n")

    using = "MOCK（不联网）" if args.mock else f"{OUTER_MODEL} / {INNER_MODEL}"
    print(f"双层 Agent 已启动 (v4 海马体版) · {using}")
    stats = outer.memory_stats()
    print(f"记忆：{stats['count']} 条 · 平均权重 {stats['avg_weight']} · {stats['path']}")
    print("命令：/quit 退出  /reset 清空历史  /hist 看历史  /mem 看记忆  /memory_stats 体检  /export 导出\n")

    def one_turn(user_input: str) -> None:
        outer_result, mode, o_usage, o_ms = outer.analyze(user_input, history)
        print(f"[外层提取]: {json.dumps(outer_result, ensure_ascii=False)}")

        payload = {k: outer_result[k] for k in FIELDS if k in outer_result}
        raw_reply, i_usage, i_ms = inner.reply(payload)
        reply, written = outer.commit_wishes(
            raw_reply,
            anchor=payload.get("experience_note", ""),
            weight=float(outer_result.get("memory_weight", DEFAULT_MEMORY_WEIGHT)),
        )
        print(f"AI: {reply}\n")
        if written:
            w0 = written[0]
            print(f"（她把这句话收进了记忆 [权重 {w0.get('weight')}]：{w0.get('content')}）\n")

        history.append({
            "user": user_input,
            "ai": reply,
            "outer": f"{payload.get('emotion')} / {payload.get('intent')}",
        })

        rec = {
            "i": len(history),
            "ts": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
            "user": user_input,
            "outer": payload,
            "inner": {"reply": reply, "prompt_hash": prompt_hash(INNER_SYSTEM_TEMPLATE)},
            "memory": {"written": [w["text"] for w in written]},
            "meta": {
                "parse_mode": mode,
                "latency_ms": {"outer": o_ms, "inner": i_ms},
                "usage": {"outer": o_usage, "inner": i_usage},
            },
        }
        try:
            store.append(rec)
        except Exception as e:  # noqa: BLE001
            print(f"[存档失败] {e}")

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
            print("（内存历史已清空，存档与记忆保留）\n")
            continue
        if user_input == "/hist":
            print(format_history(history) + "\n")
            continue
        if user_input in ("/memory_stats", "/memstats", "/memory-stats"):
            print_memory_stats(outer.memory_stats())
            print()
            continue
        if user_input == "/mem":
            print(format_recall(outer.recall("", 20)) or "（她还没有记住什么）")
            print()
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
