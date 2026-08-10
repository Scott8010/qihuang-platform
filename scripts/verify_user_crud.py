#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""用户管理全链路真实 API 验证（创建→列表→编辑→角色→改密→启停→删除）。

用完即清，不留脏数据。用法：
    E2E_BASE=https://yshealth.com.cn python scripts/verify_user_crud.py
"""
import os
import sys
import json
import time
import urllib.error
import urllib.request

BASE = os.getenv("E2E_BASE", "https://yshealth.com.cn").rstrip("/")
ADMIN_USER = os.getenv("QH_ADMIN_USER", "admin")
ADMIN_PASS = os.getenv("QH_ADMIN_PASS", "QhAdmin@2026")
TOKEN = ""
OK = 0
FAIL = 0


def call(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{BASE}{path}", data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if TOKEN:
        req.add_header("Authorization", f"Bearer {TOKEN}")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        raw = e.read().decode() or "{}"
        try:
            return e.code, json.loads(raw)
        except json.JSONDecodeError:
            return e.code, {"raw": raw}


def t(name, cond, extra=""):
    global OK, FAIL
    if cond:
        OK += 1
        print(f"  PASS  {name} {extra}")
    else:
        FAIL += 1
        print(f"  FAIL  {name} {extra}")


def main():
    global TOKEN
    print(f"目标: {BASE}\n")

    st, r = call("POST", "/admin/v1/login", {"username": ADMIN_USER, "password": ADMIN_PASS})
    if st != 200:
        print(f"[FATAL] 登录失败 {st} {r}")
        return 1
    TOKEN = r["data"]["access_token"]
    t("登录走数据库通道", r["data"].get("auth_source") == "database",
      f"source={r['data'].get('auth_source')} roles={r['data'].get('roles')}")

    uname = f"crud_probe_{int(time.time())}"
    st, r = call("POST", "/admin/v1/users", {
        "username": uname, "password": "Probe@12345",
        "display_name": "链路探针", "phone": "13800000000", "email": "probe@test.local",
    })
    t("创建用户", st == 200, f"status={st}")
    uid = r.get("data", {}).get("id", "")
    if not uid:
        print(f"[FATAL] 未拿到 user_id: {r}")
        return 1

    st, r = call("GET", "/admin/v1/users")
    me = next((u for u in r.get("data", []) if u["id"] == uid), None)
    t("列表可见新用户", me is not None)
    t("列表带租户字段", bool(me and me.get("tenant_id")), f"tenant={me.get('tenant_id') if me else None}")
    t("列表带创建时间", bool(me and me.get("created_at")))
    roles0 = [x["name"] for x in me.get("roles", [])] if me else []
    t("默认角色已挂", bool(roles0), f"roles={roles0}")

    st, _ = call("PATCH", f"/admin/v1/users/{uid}", {
        "display_name": "探针改名", "phone": "13900000000", "email": "p2@test.local"})
    t("编辑资料", st == 200, f"status={st}")
    st, r = call("GET", f"/admin/v1/users/{uid}")
    t("编辑已落库", r.get("data", {}).get("display_name") == "探针改名")

    st, _ = call("POST", "/admin/v1/roles/assign", {"user_id": uid, "role_name": "teacher"})
    t("分配角色 teacher", st == 200, f"status={st}")
    st, r = call("GET", f"/admin/v1/users/{uid}")
    t("角色已生效", "teacher" in [x["name"] for x in r.get("data", {}).get("roles", [])])
    st, _ = call("DELETE", "/admin/v1/roles/revoke", {"user_id": uid, "role_name": "teacher"})
    t("移除角色 teacher", st == 200, f"status={st}")

    st, r = call("POST", f"/admin/v1/users/{uid}/reset-password", {"password": None})
    newpw = r.get("data", {}).get("new_password", "")
    t("重置密码并回显", st == 200 and len(newpw) >= 8, f"新密码长度={len(newpw)}")

    st, _ = call("PATCH", f"/admin/v1/users/{uid}", {"status": "disabled"})
    t("停用用户", st == 200, f"status={st}")
    st, r = call("GET", f"/admin/v1/users/{uid}")
    t("停用已落库", r.get("data", {}).get("status") == "disabled")
    st, _ = call("PATCH", f"/admin/v1/users/{uid}", {"status": "active"})
    t("恢复启用", st == 200)

    st, _ = call("DELETE", f"/admin/v1/users/{uid}")
    t("删除用户", st == 200, f"status={st}")
    st, r = call("GET", "/admin/v1/users")
    rest = r.get("data", [])
    t("删除后无残留", all(u["id"] != uid for u in rest), f"平台剩余用户={len(rest)}")

    # ── 角色管理链路（权限管理页依赖） ──
    print()
    rname = f"probe_role_{int(time.time())}"
    st, r = call("POST", "/admin/v1/roles", {
        "name": rname, "display_name": "探针角色", "description": "自动化验证用",
        "perm_codes": ["core:graph:query", "core:agent:chat"],
    })
    t("新建自定义角色", st == 200, f"status={st}")
    rid = r.get("data", {}).get("id", "")

    if rid:
        st, r = call("GET", "/admin/v1/roles")
        got = next((x for x in r.get("data", []) if x["id"] == rid), None)
        t("角色列表可见", got is not None,
          f"初始权限={len(got.get('permissions', [])) if got else 0}")

        st, r = call("PUT", f"/admin/v1/roles/{rid}/permissions",
                     {"perm_codes": ["core:graph:query", "core:agent:chat", "module:3d"]})
        t("整体替换角色权限", st == 200, f"status={st}")
        st, r = call("GET", f"/admin/v1/roles/{rid}")
        t("权限变更已落库", len(r.get("data", {}).get("permissions", [])) == 3,
          f"现有={len(r.get('data', {}).get('permissions', []))} 项")

        st, r = call("DELETE", f"/admin/v1/roles/{rid}")
        t("删除自定义角色", st == 200, f"status={st}")

    # 系统角色不可删（越权防线）
    st, r = call("GET", "/admin/v1/roles")
    sys_role = next((x for x in r.get("data", []) if x["name"] == "super_admin"), None)
    if sys_role:
        st, _ = call("DELETE", f"/admin/v1/roles/{sys_role['id']}")
        t("系统角色拒绝删除", st in (400, 403, 409), f"status={st}")

    empties = [x["name"] for x in r.get("data", []) if not x.get("permissions")]
    t("无空壳角色残留", not empties, f"空壳={empties or '无'}")

    print(f"\n结果: {OK} 通过 / {FAIL} 失败")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
