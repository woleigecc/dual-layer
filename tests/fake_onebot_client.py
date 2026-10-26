# -*- coding: utf-8 -*-
"""模拟 NapCat 反向 WS 客户端，验证 main.py --ws 能收消息并回消息。"""
import asyncio
import json

import websockets

URL = 'ws://127.0.0.1:8081/'


async def main():
    async with websockets.connect(URL) as ws:
        print('[client] connected')
        events = [
            {
                "post_type": "message",
                "message_type": "private",
                "self_id": 10000,
                "user_id": 123456,
                "message_id": 1,
                "message": [{"type": "text", "data": {"text": "今天被老板骂了，烦"}}],
            },
            {
                "post_type": "message",
                "message_type": "private",
                "self_id": 10000,
                "user_id": 999999,          # 不在白名单
                "message_id": 2,
                "message": [{"type": "text", "data": {"text": "我是陌生人"}}],
            },
        ]
        for evt in events:
            await ws.send(json.dumps(evt, ensure_ascii=False))
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=12)
                print('[client] 收到动作:', raw[:200])
            except asyncio.TimeoutError:
                print('[client] 12 秒内没有收到回复（可能是白名单拦截，符合预期）')


asyncio.run(main())
