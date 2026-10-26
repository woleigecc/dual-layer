# -*- coding: utf-8 -*-
"""生成 README 用的架构图（白色背景，适合 GitHub 展示）。

输出到 dual-layer/docs/：
  architecture.png     总体数据流与权限边界
  memory-lifecycle.png 记忆新陈代谢（打分 / 回忆 / 淘汰）
  class-diagram.png    类结构与 FrozenMemoryHandle 权限拦截
"""

import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch
from matplotlib import font_manager

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), "docs")
os.makedirs(OUT, exist_ok=True)

for f in (r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\msyhbd.ttc"):
    if os.path.exists(f):
        font_manager.fontManager.addfont(f)

plt.rcParams["font.family"] = "Microsoft YaHei"
plt.rcParams["axes.unicode_minus"] = False

INK, MUTED = "#1f2328", "#57606a"
GREEN, RED, BLUE, PURPLE, ORANGE = "#1a7f37", "#cf222e", "#0969da", "#8250df", "#bc4c00"
BG_OUTER, BG_INNER, BG_MEM, BG_GUARD = "#ddf4ff", "#fff8c5", "#f6f8fa", "#fff5f5"


def box(ax, x, y, w, h, text, fc, ec, fs=13, color=INK, bold=False, align="center", pad=0.03):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle=f"round,pad=0.012,rounding_size=0.03",
                                linewidth=1.6, facecolor=fc, edgecolor=ec, zorder=2))
    if align == "center":
        ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=fs,
                color=color, zorder=3, linespacing=1.6,
                fontweight="bold" if bold else "normal")
    else:
        ax.text(x + pad, y + h / 2, text, ha="left", va="center", fontsize=fs,
                color=color, zorder=3, linespacing=1.6,
                fontweight="bold" if bold else "normal")


def arrow(ax, p1, p2, color=INK, lw=1.7, ls="-", rad=0.0):
    ax.add_patch(FancyArrowPatch(p1, p2, arrowstyle="-|>", mutation_scale=16,
                                 linewidth=lw, color=color, linestyle=ls, zorder=1,
                                 connectionstyle=f"arc3,rad={rad}"))


def label(ax, x, y, t, color=MUTED, fs=10.5, ha="center", va="center", bold=False):
    ax.text(x, y, t, color=color, fontsize=fs, ha=ha, va=va, zorder=4,
            fontweight="bold" if bold else "normal", linespacing=1.5)


def cross(ax, x, y, s=0.10, color=RED, lw=3.2):
    ax.plot([x - s, x + s], [y - s, y + s], color=color, lw=lw, solid_capstyle="round", zorder=6)
    ax.plot([x - s, x + s], [y + s, y - s], color=color, lw=lw, solid_capstyle="round", zorder=6)


# ══════════════════════ 图 1：总体数据流 ══════════════════════

def fig_architecture():
    fig, ax = plt.subplots(figsize=(13.2, 7.4), dpi=170)
    ax.set_xlim(0, 13.2); ax.set_ylim(0, 7.4); ax.axis("off")
    fig.patch.set_facecolor("white")

    ax.text(0.35, 7.02, "双层 Agent 心智框架", fontsize=22, fontweight="bold", color=INK)
    ax.text(0.35, 6.62, "外层全知，内层受限 —— 记忆属于她，但钥匙在外层手里",
            fontsize=11.5, color=MUTED)

    box(ax, 0.35, 2.55, 1.55, 0.95, "用户原话", "#ffffff", "#8c959f", fs=13, bold=True)
    box(ax, 2.55, 2.25, 2.75, 1.55,
        "OuterLayer\n外层 · 全知\n\n原话 + 历史 + 记忆", BG_OUTER, BLUE, fs=12.5)
    box(ax, 6.35, 2.25, 2.75, 1.55,
        "InnerLayer\n内层 · 受限\n\n只有情绪标签 + 体验笔记", BG_INNER, ORANGE, fs=12.5)
    box(ax, 9.85, 2.55, 1.55, 0.95, "回复", "#ffffff", "#8c959f", fs=13, bold=True)
    box(ax, 2.55, 5.10, 2.75, 1.20,
        "memory.json\n她的海马体\n第一人称 + 情绪滤镜 + 权重", "#f6f8fa", "#6e7781", fs=11.5)

    arrow(ax, (1.90, 3.02), (2.55, 3.02))
    label(ax, 2.22, 3.24, "原话", fs=9.5)
    arrow(ax, (5.30, 3.02), (6.35, 3.02))
    label(ax, 5.82, 3.52, "emotion\nintent\nnote", BLUE, fs=9)
    arrow(ax, (9.10, 3.02), (9.85, 3.02))

    # 外层 -> 记忆（绿色，可读写）
    arrow(ax, (3.30, 3.80), (3.30, 5.10), GREEN, 2.0)
    arrow(ax, (4.20, 5.10), (4.20, 3.80), GREEN, 2.0)
    label(ax, 2.98, 4.45, "read_memory()\nwrite_memory()\nrecall()", GREEN, fs=9.5, ha="right", bold=True)

    # 内层 -> 记忆（红色，被拦截）
    arrow(ax, (7.10, 3.80), (5.35, 4.95), RED, 2.0, ls=(0, (4, 3)), rad=-0.16)
    cross(ax, 6.05, 4.42)
    label(ax, 6.30, 4.72, "FrozenMemoryHandle", RED, fs=10.5, ha="left", bold=True)
    label(ax, 6.30, 4.46, "调用即 PermissionError_", RED, fs=9.5, ha="left")

    box(ax, 6.35, 1.12, 2.75, 0.72,
        "签名里没有 user_input\n物理上拿不到原话", BG_GUARD, "#ff8182", fs=9.5, color="#82071e")
    arrow(ax, (7.72, 2.25), (7.72, 1.84), "#ff8182", 1.2)

    box(ax, 2.55, 1.12, 2.75, 0.72,
        "潜意识解锁器\n代她回忆、代她写入", BG_OUTER, "#54aeff", fs=9.5, color="#0a3069")
    arrow(ax, (3.92, 2.25), (3.92, 1.84), "#54aeff", 1.2)

    ax.plot([0.35, 0.95], [0.42, 0.42], color=GREEN, lw=2.4)
    label(ax, 1.03, 0.42, "外层可读写记忆", GREEN, fs=10, ha="left")
    ax.plot([3.30, 3.90], [0.42, 0.42], color=RED, lw=2.4, ls=(0, (4, 3)))
    label(ax, 3.98, 0.42, "内层无访问权（运行时抛异常）", RED, fs=10, ha="left")

    fig.savefig(os.path.join(OUT, "architecture.png"), bbox_inches="tight",
                facecolor="white", pad_inches=0.25)
    plt.close(fig)
    print("saved docs/architecture.png")


# ══════════════════════ 图 2：记忆新陈代谢 ══════════════════════

def fig_memory_lifecycle():
    fig, ax = plt.subplots(figsize=(13.2, 5.6), dpi=170)
    ax.set_xlim(0, 13.2); ax.set_ylim(0, 5.6); ax.axis("off")
    fig.patch.set_facecolor("white")

    ax.text(0.35, 5.22, "记忆的新陈代谢", fontsize=20, fontweight="bold", color=INK)
    ax.text(0.35, 4.86, "她表达愿望 → 外层打分写入 → 越回忆越深刻 → 太弱就被遗忘",
            fontsize=11, color=MUTED)

    box(ax, 0.35, 2.45, 2.5, 1.15, "内层\n[我想记住：…]", BG_INNER, ORANGE, fs=11.5)
    box(ax, 3.45, 2.45, 2.5, 1.15, "外层\n解析 + 打分\nweight 1.0~5.0", BG_OUTER, BLUE, fs=11.5)
    box(ax, 6.55, 2.45, 2.5, 1.15, "memory.json\ncontent / weight\nlast_accessed", "#f6f8fa", "#6e7781", fs=11)
    box(ax, 9.65, 2.45, 3.2, 1.15, "回忆注入\n过滤 <1.5 · 取 top5\n被想起 +0.1", "#dafbe1", GREEN, fs=11)

    arrow(ax, (2.85, 3.02), (3.45, 3.02))
    label(ax, 3.15, 3.28, "心愿", fs=9.5)
    arrow(ax, (5.95, 3.02), (6.55, 3.02))
    label(ax, 6.25, 3.28, "写入", fs=9.5)
    arrow(ax, (9.05, 3.02), (9.65, 3.02))
    label(ax, 9.35, 3.28, "检索", fs=9.5)
    arrow(ax, (11.25, 2.45), (11.25, 1.55), GREEN, 1.6)
    label(ax, 11.25, 1.28, "权重上涨，印象更深", GREEN, fs=9.5)

    box(ax, 3.45, 0.50, 5.6, 1.05,
        "超过 50 条 → 淘汰最弱的：weight 升序，同分比 last_accessed\n"
        "weight ≥ 4.5 的核心记忆永不删除",
        BG_GUARD, "#ff8182", fs=10.5, color="#82071e")
    arrow(ax, (6.55, 2.45), (6.20, 1.55), RED, 1.5, ls=(0, (4, 3)))

    ax.plot([0.35, 12.85], [4.24, 4.24], color="#d0d7de", lw=6, solid_capstyle="butt", zorder=0)
    for x, w, c in [(0.95, "1.0", "#8c959f"), (4.40, "2.0", "#8c959f"),
                    (7.60, "3.5", ORANGE), (11.40, "4.5+", GREEN)]:
        ax.plot([x], [4.24], marker="o", ms=9, color=c, zorder=2)
        label(ax, x, 4.50, w, c, fs=10, bold=True)
    label(ax, 0.35, 4.00, "日常闲聊", MUTED, fs=9, ha="left")
    label(ax, 6.95, 4.00, "重要情绪", ORANGE, fs=9, ha="left")
    label(ax, 10.55, 4.00, "核心记忆 · 不删", GREEN, fs=9, ha="left")

    fig.savefig(os.path.join(OUT, "memory-lifecycle.png"), bbox_inches="tight",
                facecolor="white", pad_inches=0.25)
    plt.close(fig)
    print("saved docs/memory-lifecycle.png")


# ══════════════════════ 图 3：类结构 + 权限拦截 ══════════════════════

def fig_class_diagram():
    fig, ax = plt.subplots(figsize=(13.0, 7.0), dpi=170)
    ax.set_xlim(0, 13.0); ax.set_ylim(0, 7.0); ax.axis("off")
    fig.patch.set_facecolor("white")

    ax.text(0.35, 6.62, "类结构：记忆由外层代管，内层只拿封条", fontsize=19,
            fontweight="bold", color=INK)
    ax.text(0.35, 6.24, "两个类都有 inner_memory_store，但一个是真身，一个是 FrozenMemoryHandle",
            fontsize=10.5, color=MUTED)

    # OuterLayer
    box(ax, 0.45, 3.30, 3.30, 2.35, "", BG_OUTER, BLUE)
    ax.text(0.65, 5.30, "OuterLayer", fontsize=13, fontweight="bold", color=BLUE, zorder=3)
    ax.text(0.65, 4.98, "全知层 · 潜意识解锁器", fontsize=9.5, color=MUTED, zorder=3)
    ax.plot([0.45, 3.75], [4.82, 4.82], color="#54aeff", lw=1.0, zorder=3)
    ax.text(0.65, 4.55, "inner_memory_store = 真身", fontsize=9.5, color=INK, zorder=3)
    ax.text(0.65, 4.22, "analyze()  读到原话+历史+记忆", fontsize=9.5, color=INK, zorder=3)
    ax.text(0.65, 3.94, "recall()   代她回忆", fontsize=9.5, color=INK, zorder=3)
    ax.text(0.65, 3.66, "commit_wishes()  代她写入", fontsize=9.5, color=INK, zorder=3)

    # InnerLayer
    box(ax, 0.45, 0.75, 3.30, 2.05, "", BG_INNER, ORANGE)
    ax.text(0.65, 2.52, "InnerLayer", fontsize=13, fontweight="bold", color=ORANGE, zorder=3)
    ax.text(0.65, 2.20, "受限层 · 记忆的主人", fontsize=9.5, color=MUTED, zorder=3)
    ax.plot([0.45, 3.75], [2.05, 2.05], color="#e8a33d", lw=1.0, zorder=3)
    ax.text(0.65, 1.78, "inner_memory_store = 封条", fontsize=9.5, color=INK, zorder=3)
    ax.text(0.65, 1.45, "reply(payload)  只会说话", fontsize=9.5, color=INK, zorder=3)
    ax.text(0.65, 1.12, "没有任何查询记忆的方法", fontsize=9.5, color=RED, zorder=3)

    # FrozenMemoryHandle
    box(ax, 4.55, 0.75, 3.05, 2.05, "", BG_GUARD, RED)
    ax.text(4.75, 2.52, "FrozenMemoryHandle", fontsize=12.5, fontweight="bold", color=RED, zorder=3)
    ax.text(4.75, 2.20, "只有归属，没有权限（as_inner_handle 生成）", fontsize=9, color=MUTED, zorder=3)
    ax.plot([4.55, 7.60], [2.05, 2.05], color="#ff8182", lw=1.0, zorder=3)
    ax.text(4.75, 1.78, "read_memory()  → raise", fontsize=9.5, color=INK, zorder=3)
    ax.text(4.75, 1.50, "write_memory() → raise", fontsize=9.5, color=INK, zorder=3)
    ax.text(4.75, 1.22, "recall() / entries() → raise", fontsize=9.5, color=INK, zorder=3)
    ax.text(4.75, 0.96, "PermissionError_", fontsize=9.5, color=RED, zorder=3, fontweight="bold")

    # InnerMemoryStore
    box(ax, 8.30, 0.75, 4.30, 2.05, "", "#f6f8fa", "#6e7781")
    ax.text(8.50, 2.52, "InnerMemoryStore", fontsize=12.5, fontweight="bold", color=INK, zorder=3)
    ax.text(8.50, 2.20, "记忆真身（只允许外层持有）", fontsize=9.5, color=MUTED, zorder=3)
    ax.plot([8.30, 12.60], [2.05, 2.05], color="#afb8c1", lw=1.0, zorder=3)
    ax.text(8.50, 1.78, "read_memory() / write_memory()", fontsize=9.5, color=INK, zorder=3)
    ax.text(8.50, 1.50, "recall()  权重奖励 +0.1", fontsize=9.5, color=INK, zorder=3)
    ax.text(8.50, 1.22, "stats()   体检报告", fontsize=9.5, color=INK, zorder=3)
    ax.text(8.50, 0.96, "→ memory.json", fontsize=9.5, color=MUTED, zorder=3)

    # Outer -> Store：从上方绕过去，避免穿过 FrozenMemoryHandle
    ax.plot([3.75, 11.05], [4.55, 4.55], color=GREEN, lw=2.0, zorder=1,
            solid_capstyle="round")
    ax.plot([11.05, 11.05], [4.55, 2.95], color=GREEN, lw=2.0, zorder=1,
            solid_capstyle="round")
    arrow(ax, (11.05, 2.95), (11.05, 2.80), GREEN, 2.0)
    label(ax, 7.20, 4.78, "持有真身 · 可读写", GREEN, fs=10, bold=True)

    # Inner -> Frozen（拿到的是封条）
    arrow(ax, (3.75, 1.70), (4.55, 1.70), "#e8a33d", 1.8)


    # Frozen -> Store（红，被拦截）
    arrow(ax, (7.60, 1.62), (8.30, 1.62), RED, 2.0, ls=(0, (4, 3)))
    cross(ax, 7.95, 1.62, s=0.07)

    # 底部说明
    box(ax, 0.45, 0.05, 12.15, 0.48,
        "权限矩阵：OuterLayer → 读写允许　　InnerLayer → 只持有引用，调用即抛异常（禁止）",
        "#ffffff", "#d0d7de", fs=10, color=MUTED)

    fig.savefig(os.path.join(OUT, "class-diagram.png"), bbox_inches="tight",
                facecolor="white", pad_inches=0.25)
    plt.close(fig)
    print("saved docs/class-diagram.png")


if __name__ == "__main__":
    fig_architecture()
    fig_memory_lifecycle()
    fig_class_diagram()
