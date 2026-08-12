#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
岐黄智脑平台 · 运维告警推送
复用 8601 中台已配置的 PushPlus token，向老黄微信推送运维事件。
用法:
    python3 qihuang_alert.py "<标题>" "<内容>"
退出码: 0=推送成功 / 1=失败或缺少 token
"""
import sys
import os
import json
import urllib.request

# 按优先级查找 PushPlus token（仅在本地 .env，不硬编码）
ENV_FILES = [
    "/root/qihuang/app/.env",
    "/root/qihuang_platform/.env",
]


def get_token() -> str | None:
    for f in ENV_FILES:
        if os.path.exists(f):
            try:
                for line in open(f, encoding="utf-8"):
                    line = line.strip()
                    if line.startswith("PUSHPLUS_TOKEN="):
                        return line.split("=", 1)[1].strip().strip('"').strip("'")
            except Exception:
                continue
    return None


def push(title: str, content: str) -> bool:
    token = get_token()
    if not token:
        print("WARN: PUSHPLUS_TOKEN not found in env files, skip push")
        return False
    url = "http://www.pushplus.plus/send"
    payload = {
        "token": token,
        "title": title,
        "content": content,
        "template": "txt",
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            resp = json.loads(r.read().decode("utf-8", "replace"))
            ok = resp.get("code") == 200
            print("push result:", resp.get("msg", resp))
            return ok
    except Exception as e:
        print("push error:", e)
        return False


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("usage: qihuang_alert.py <title> <content>")
        sys.exit(1)
    ok = push(sys.argv[1], sys.argv[2])
    sys.exit(0 if ok else 1)
