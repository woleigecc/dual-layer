# -*- coding: utf-8 -*-
"""内层的海马体模块。

记忆在哲学上属于 InnerLayer（是她的经历），但访问权在外层（潜意识解锁器）。
对外只暴露三个东西：
- InnerMemoryStore   记忆真身（只给 OuterLayer）
- FrozenMemoryHandle 内层持有的封条（调用即越权异常）
- format_recall      把回忆拼成文本的工具
"""

from .store import (
    FrozenMemoryHandle,
    InnerMemoryStore,
    PermissionError_,
    format_recall,
)

__all__ = [
    "InnerMemoryStore",
    "FrozenMemoryHandle",
    "PermissionError_",
    "format_recall",
]
