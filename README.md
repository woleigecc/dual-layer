# 双层 Agent 心智框架 · 最简 CLI

通过**信息隔离**让内层模型只能说"我觉得……"而说不出完整原因，从而摆脱全知全能的表演感。

## 目录结构

```
dual-layer/
├── main.py            # 全部逻辑（外层 / 内层 / 健壮 JSON / 主循环 / 存档）
├── requirements.txt   # 依赖清单
├── .env.example       # 环境变量模板（复制成 .env 用）
├── tests/             # JSON 解析器测试
├── LICENSE            # MIT
└── README.md          # 本文件
```

单文件跑通，不接数据库、不接 QQ、不接任何框架。

## 安装

```bash
pip install -r requirements.txt
```

> **请将 `.env.example` 复制并重命名为 `.env`，填入你的 DeepSeek API Key。**

## 配置 API Key（两种方式，任选）

**方式一：`.env` 文件（推荐）**

```bash
cp .env.example .env      # Windows: copy .env.example .env
# 然后编辑 .env，把 DEEPSEEK_API_KEY 改成你自己的 key
```

`main.py` 启动时用 **python-dotenv** 自动读取脚本同目录的 `.env`
（没装 python-dotenv 时会退回内置的零依赖解析，照样能跑）。
系统环境变量优先，`.env` 不会覆盖已存在的值。

**方式二：系统环境变量**

```bash
# Windows (cmd)
set DEEPSEEK_API_KEY=sk-你的key

# Windows (PowerShell)
$env:DEEPSEEK_API_KEY="sk-你的key"

# Linux / macOS
export DEEPSEEK_API_KEY=sk-你的key
```

可选环境变量：

| 变量 | 默认 | 说明 |
|---|---|---|
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com` | 兼容其它 OpenAI 协议端点 |
| `OUTER_MODEL` | `deepseek-chat` | 外层模型 |
| `INNER_MODEL` | `deepseek-chat` | 内层模型（可换 deepseek-reasoner 做内省） |
| `MAX_HISTORY_TURNS` | `12` | 外层只看最近 N 轮历史 |

## 运行

```bash
python main.py            # 真跑
python main.py --mock     # 不联网，自检闭环（不需要 key）
python main.py --once "我今天心情不好"   # 只跑一句
```

交互命令：`/quit` 退出、`/reset` 清空历史、`/hist` 看历史。

## 数据流向（铁律）

```
用户原话 ─┬─→ OuterLayer（全知：原话 + 历史）─→ {"emotion","intent","reaction"}
          │                                            │
          │                                            ↓
          └──✗ 不进内层                         InnerLayer（受限：只见 JSON）
                                                       │
                                                       ↓
                                              "我不知道为什么，我就是觉得……"
```

代码层面的保证：

- `inner_layer(outer_result)` 的**签名里没有** `user_input` / `history`，物理上拿不到。
- 内层若收到 `user` / `history` 字段会直接抛 `ValueError`（防止未来手滑把全量塞进去）。
- 历史只拼进外层的 user message，内层只 receive `emotion / intent / reaction`。

## JSON 解析的健壮性

`parse_json_loose()` 四级兜底：

1. 直接 `json.loads`
2. 剥掉 ` ```json ` 代码块再 loads
3. 从任意废话里找**括号配平**的 `{...}` 再 loads（能正确处理字符串里的花括号）
4. 还不行就用正则按字段别名硬抠（`emotion/情绪/feeling` 等）
5. 全部失败 → 返回默认值，**永不崩**

## 下一步可以加什么（现在故意没做）

- 外层记忆：把 `emotion/intent` 序列压成"关系状态"，而不是塞全量历史
- 内层"身体状态"：随机心情、疲劳度，让内层有额外的私有变量
- 双内层：一个说话、一个只在心里碎碎念（不输出）
- 让内层偶尔"拒绝"：当 intent 与自身状态冲突时，它可以不配合

## 存档（v3 新增）

每轮对话自动落盘，**追加写，不重写整文件**。

- 主存：`data/turns.jsonl`，每行一条 JSON
- 轮转：单文件超过 5MB 自动新建 `turns-2.jsonl`、`turns-3.jsonl`…（`ROTATE_MB` 可调）
- 导出：`python main.py --export out.json` 或对话里输入 `/export`
- 恢复：`python main.py --resume` 从存档接着聊
- 目录：默认在脚本旁的 `data/`，可用 `--data-dir` 或 `DATA_DIR` 改

每条记录包含：轮次、时间、用户原话、外层三字段、内层回复、prompt hash、解析方式、耗时、token 用量。

> 注意：`user` 原文只用于分析，**不会回流给内层**——`inner_layer` 的隔离校验仍在（收到 `user`/`history` 直接抛异常）。

## 接入 QQ（NapCat + OneBot v11）

`main.py` 可以当 **OneBot v11 WebSocket 服务端**用，由 NapCat 主动连过来。

### 1. 启动服务

```bash
python main.py --ws --allow-uin 你的QQ号
# 默认监听 ws://127.0.0.1:8080/
# 改端口/地址： --ws-port 8080 --ws-host 0.0.0.0
```

`--allow-uin` 可重复，用来做白名单；留空表示谁都能聊（不建议）。

### 2. 配置 NapCat

1. 打开 NapCat WebUI
2. 进入 **网络配置**
3. 新建 **WebSocket 客户端**（反向 WS）
4. URL 填 `ws://127.0.0.1:8080/`
   - 如果 main.py 跑在另一台机器，填 `ws://那台机器的IP:8080/`，同时 `--ws-host 0.0.0.0`
5. 保存并启用

启用后 NapCat 会连到 `main.py`，私聊机器人的每条消息都会走「外层提取 → 内层回复」。

### 3. 工作方式

```
QQ 私聊
  → NapCat（OneBot v11）
  → main.py --ws（事件回调）
      → outer_layer(用户原话 + 历史)        # 全知
      → inner_layer(emotion/intent/note)   # 受限，看不到原话
  → send_private_msg 回 QQ
  → 同时写进 data/turns.jsonl 存档
```

⚠️ **同一个 QQ 号同一时间只能有一个机器人服务在收消息**，别和别的桥接同时开，否则会打架（消息被两边抢、重复回复）。

### 4. 本地自测（不需要 NapCat）

```bash
python main.py --ws --mock --allow-uin 123456 --ws-port 8081
python tests/fake_onebot_client.py
```

第二个脚本会模拟 NapCat 发一条私聊，并打印 main.py 回的 `send_private_msg` 动作。

## 记忆（海马体）

记忆在哲学上属于内层（是她的经历），但**访问权在外层**。

```
memory/
├── store.py        # InnerMemoryStore（真身） + FrozenMemoryHandle（封条）
└── memory.json     # 她的海马体（.gitignore，绝不入库）
```

| 类 | 持有的东西 | 能做什么 |
|---|---|---|
| `OuterLayer` | `inner_memory_store` = 真身 | `recall()` / `write_memory()` / `read_memory()` —— 潜意识解锁器 |
| `InnerLayer` | `inner_memory_store` = **封条** | 什么都不能做，调用即 `PermissionError_` |

### 写入：她表达愿望，外层代执行

内层在回复末尾可以写一行：

```
[我想记住：今天是母亲离世的日子，他把这件事交到我手上，我心里一沉。]
```

这一行不会被发出去；外层解析后，以**第一人称 + 情绪滤镜 + 事实锚点**写进 `memory.json`。

### 读取：外层回忆，融进笔记

外层每轮按「最近 + 关键词」挑 ≤5 条，注入自己的 prompt，然后把影响**融进** `experience_note`。
内层始终只看到那一段笔记，看不到记忆条目本身。

### 怎么验证

**1) 权限拦截（不花钱、不需要 key）**

```bash
python tests/test_memory.py
```

其中 `test_inner_cannot_touch_memory` 会断言：内层调用 `read_memory()` / `write_memory()` / `recall()` 全部抛越权异常。

**2) 她能不能主动触发记忆写入**

CLI：

```bash
python main.py
你: 今天是我妈的忌日，这件事你别忘
```

看到这行就成功了：

```
（她把这句话收进了记忆：今天是母亲离世的日子，他把这件事交到我手里，我心里一沉……）
```

再输入 `/mem` 能列出记忆条目。

QQ 模式：给机器人发一句分量重的话，服务端日志会出现：

```
[qq] 3473537643: 今天是我妈的忌日，这件事你别忘
[记忆] 写入了 1 条
```

**3) 看统计**

```bash
python main.py --mem-stats
```

### 注意

- 记忆按 `RECALL_TOP_K`（默认 5）注入，太多会稀释注意力
- 单文件上限 500 条，超出滚动淘汰最老的
- `memory/memory.json` 已进 `.gitignore` —— 这是私密经历，别推上 GitHub
