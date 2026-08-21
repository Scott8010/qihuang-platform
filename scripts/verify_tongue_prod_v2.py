# -*- coding: utf-8 -*-
"""生产验真 v2：真 GT 舌图 HMAC 打 /api/v1/agent/tongue/analyze，验证 Layer2 规则层上线。

- 签名契约：msg={app_key}\\n{method}\\n{path}\\n{ts}\\n{nonce}\\n{body}，HMAC-SHA256 hex
- headers: X-App-Key / X-Signature / X-Timestamp / X-Nonce
- secret 仅内存使用，绝不打印
- 图：/tmp/tongue_probe/imgs/ 下带真值的探针图（1417=黄腻 1350=黄腻 1025=白腻 363=薄白）
- 断言：mode=vision；syndrome_hints=[{name,confidence,source:"rule"}]；
  黄腻图 → 湿热内蕴倾向；combined_syndrome 与 hints 名称一致
"""
import base64
import hashlib
import hmac
import json
import mimetypes
import sys
import time
import urllib.error
import urllib.request
import uuid

from dotenv import load_dotenv

load_dotenv("/root/qihuang_platform/.env")
from qihuang_platform.db.config import SessionLocal
from qihuang_platform.db.models import ApiKey

APP_KEY = "ak_7e5722682d954b39"

CASES = [
    # (图, 期望倾向名包含)
    ("1417.jpg", "湿热内蕴倾向"),
    ("1350.jpg", "湿热内蕴倾向"),
    ("1025.jpg", "湿浊内蕴倾向"),
    ("363.jpg", None),  # 薄白苔+可能健康 → hints 可为空
]


def call_analyze(secret, image_path):
    mime = mimetypes.guess_type(image_path)[0] or "image/jpeg"
    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")
    body = json.dumps({"image": "data:%s;base64,%s" % (mime, b64)}, ensure_ascii=False)

    method, path = "POST", "/api/v1/agent/tongue/analyze"
    ts = str(int(time.time()))
    nonce = uuid.uuid4().hex[:16]
    msg = "%s\n%s\n%s\n%s\n%s\n%s" % (APP_KEY, method, path, ts, nonce, body)
    sig = hmac.new(secret.encode("utf-8"), msg.encode("utf-8"), hashlib.sha256).hexdigest()

    req = urllib.request.Request(
        "http://127.0.0.1:8602%s" % path,
        data=body.encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "X-App-Key": APP_KEY,
            "X-Signature": sig,
            "X-Timestamp": ts,
            "X-Nonce": nonce,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


def main():
    db = SessionLocal()
    try:
        key = db.query(ApiKey).filter_by(app_key=APP_KEY).first()
        if not key:
            print("FATAL: 未找到 API Key", APP_KEY)
            return 2
        secret = key.app_secret  # 仅内存
        print("key 状态:", key.status, "| tenant:", key.tenant_id)
    finally:
        db.close()

    all_ok = True
    for fname, expect_name in CASES:
        path = "/tmp/tongue_probe/imgs/%s" % fname
        status, out = call_analyze(secret, path)
        data = out.get("data") or {}
        mode = data.get("mode")
        tongue = data.get("tongue") or {}
        hints = tongue.get("syndrome_hints") or []
        combined = data.get("combined_syndrome") or []
        coat = tongue.get("coating") or {}

        ok = status == 200 and out.get("code") == 0 and mode == "vision"
        # 规则层结构断言
        if ok and hints:
            struct_ok = all(
                isinstance(h, dict) and h.get("source") == "rule"
                and 0 < h.get("confidence", 0) <= 0.9 and h.get("name")
                for h in hints
            )
            names = [h["name"] for h in hints]
            ok = ok and struct_ok and combined == names
        elif ok and not hints:
            ok = ok and combined == []  # 健康舌 → 双空
        # 期望倾向断言
        if ok and expect_name:
            ok = any(expect_name in h.get("name", "") for h in hints)

        print("[%s] HTTP %s mode=%s coat(色/厚/质)=%s/%s/%s hints=%s combined=%s → %s" % (
            fname, status, mode, coat.get("color"), coat.get("thickness"), coat.get("quality"),
            json.dumps(hints, ensure_ascii=False), json.dumps(combined, ensure_ascii=False),
            "PASS" if ok else "FAIL"))
        all_ok = all_ok and ok

    print("VERIFY:", "PASS" if all_ok else "FAIL")
    return 0 if all_ok else 5


if __name__ == "__main__":
    raise SystemExit(main())
