#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生产 API 层验真：登录拿 token -> 拉 /admin/v1/plans -> 断言新字段透传"""
import json
import urllib.request
import urllib.error

BASE = "https://111.231.63.73"
USER = "admin"
PASS = "QhAdmin@2026"

ctx_skip = None  # 生产自签证书


def http(method, path, token=None, body=None):
    url = BASE + path
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    # 跳过自签证书校验
    import ssl
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        with urllib.request.urlopen(req, timeout=30, context=ctx) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8"))
        except Exception:
            return e.code, {"raw": e.read().decode("utf-8", "ignore")}


def main():
    print("=== [1] 登录 /admin/v1/login ===")
    st, resp = http("POST", "/admin/v1/login", body={"username": USER, "password": PASS})
    print("HTTP", st, "| code=", resp.get("code"), "| msg=", resp.get("message"))
    if resp.get("code") != 0 and "token" not in (resp.get("data") or {}):
        # 兼容不同返回结构
        print("登录返回体:", json.dumps(resp, ensure_ascii=False)[:500])
    token = None
    d = resp.get("data") or {}
    for k in ("token", "access_token", "jwt"):
        if k in d:
            token = d[k]
            break
    if not token:
        # 某些实现 token 直接挂在顶层
        token = resp.get("token") or resp.get("access_token")
    if not token:
        print("!!! 拿不到 token，无法继续。先看登录返回体。")
        return
    print("TOKEN 前缀:", token[:18], "...")

    print("\n=== [2] 拉 /admin/v1/plans (带 token) ===")
    st, resp = http("GET", "/admin/v1/plans", token=token)
    print("HTTP", st, "| code=", resp.get("code"), "| msg=", resp.get("message"))
    plans = resp.get("data")
    if not isinstance(plans, list):
        print("plans 非列表，返回体:", json.dumps(resp, ensure_ascii=False)[:600])
        return

    print("\n=== [3] 逐套餐核对新字段 ===")
    ok_all = True
    for p in plans:
        name = p.get("plan_name")
        feats = p.get("features_json") or {}
        custom_skin = feats.get("custom_skin")
        price = p.get("price_cents")
        calls = p.get("month_calls")
        toks = p.get("month_tokens")
        qps = p.get("qps")
        scene = p.get("scene_type")
        status = p.get("status")
        # 断言字段存在
        miss = [k for k, v in {
            "price_cents": price, "month_calls": calls, "month_tokens": toks,
            "qps": qps, "scene_type": scene, "status": status,
        }.items() if v is None]
        line = (f"- {name:12} | price={price} cents | month_calls={calls} | "
                f"month_tokens={toks} | qps={qps} | scene={scene} | status={status} | "
                f"custom_skin={custom_skin}")
        print(line)
        if miss:
            ok_all = False
            print(f"    !!! 缺字段: {miss}")
        # 客户成功预期：仅 enterprise 开
        if name == "enterprise" and custom_skin is not True:
            print("    !!! 企业版 custom_skin 应为 True")
            ok_all = False
        if name != "enterprise" and custom_skin is True:
            print(f"    !!! {name} custom_skin 应为 False")
            ok_all = False

    print("\n=== 结论 ===")
    print("后端新字段全部透传 + 客户成功开关符合拍板(仅企业版开):", "YES" if ok_all else "NO")


if __name__ == "__main__":
    main()
