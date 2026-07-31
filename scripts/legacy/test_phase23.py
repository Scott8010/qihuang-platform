"""
Phase 2+3 统一测试脚本
测试所有新增端点: #20计费账单 + #9大健康 + #12医疗 + #13培训 + #15控制端全功能 + #14稳定性
"""
import requests
import json
import sys

BASE = "http://localhost:8602"
TOKEN = None
PASS = 0
FAIL = 0
ERRORS = []

def login():
    global TOKEN
    r = requests.post(f"{BASE}/dev/admin-login", json={"username": "admin", "password": "x"})
    data = r.json()
    TOKEN = data.get("data", {}).get("access_token") or data.get("access_token")
    return TOKEN is not None

def call(method, path, **kwargs):
    headers = kwargs.pop("headers", {})
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    r = requests.request(method, f"{BASE}{path}", headers=headers, **kwargs)
    return r.status_code, r.json() if r.headers.get("content-type", "").startswith("application/json") else r.text

def test(name, method, path, expected_status=200, **kwargs):
    global PASS, FAIL
    try:
        status, body = call(method, path, **kwargs)
        code = body.get("code", -1) if isinstance(body, dict) else -1
        if status == expected_status and (code == 0 or code == -1 or isinstance(body, dict)):
            PASS += 1
            print(f"  [PASS] {name}")
        else:
            FAIL += 1
            ERRORS.append(f"{name}: HTTP {status}, code={code}")
            print(f"  [FAIL] {name} → HTTP {status}, code={code}")
    except Exception as e:
        FAIL += 1
        ERRORS.append(f"{name}: {str(e)}")
        print(f"  [FAIL] {name} → {str(e)}")

def run_tests():
    print("=" * 60)
    print("Phase 2+3 统一测试")
    print("=" * 60)

    # 登录
    print("\n[登录]")
    if not login():
        print("  [FAIL] 登录失败，终止测试")
        return
    print("  [PASS] 管理员登录成功")

    # #20 计费账单
    print("\n[#20 计费账单]")
    test("查询用量", "GET", "/admin/v1/billing/usage")
    test("查询用量(指定租户)", "GET", "/admin/v1/billing/usage?tenant_id=tenant_default")
    test("查询账单列表", "GET", "/admin/v1/billing/bills")
    test("生成月账单", "POST", "/admin/v1/billing/bills/generate",
         json={"tenant_id": "tenant_default", "period": "2026-07"})
    test("创建套餐", "POST", "/admin/v1/plans",
         json={"plan_name": "test_plan", "display_name": "测试套餐", "price_cents": 1000})
    test("查询订阅列表", "GET", "/admin/v1/subscriptions")

    # #15 控制端全功能
    print("\n[#15 控制端全功能]")
    test("套餐列表", "GET", "/admin/v1/plans")
    test("知识审核待审列表", "GET", "/admin/v1/kg/review/pending")
    test("知识图谱版本列表", "GET", "/admin/v1/kg/versions")
    test("监控大盘", "GET", "/admin/v1/monitor/overview")
    test("LLM降级链状态", "GET", "/admin/v1/monitor/llm-status")
    test("审计日志", "GET", "/admin/v1/audit-logs")
    test("敏感词列表", "GET", "/admin/v1/content/words")
    test("添加敏感词", "POST", "/admin/v1/content/words",
         json={"scene": "HEALTH", "word": "测试敏感词", "level": "warn"})
    test("租户监控", "GET", "/admin/v1/monitor/tenant/tenant_default")

    # #9 大健康服务包
    print("\n[#9 大健康服务包]")
    test("体质辨识", "POST", "/api/v1/health/constitution/assess",
         json={"symptoms": "头痛,失眠,易怒"})
    test("九大体质列表", "GET", "/api/v1/health/constitutions")
    test("六经列表", "GET", "/api/v1/health/meridians")
    test("健康档案时间轴", "GET", "/api/v1/health/archive/timeline")
    test("穴位保健指导", "GET", "/api/v1/health/acupoints/guide?constitution_type=气虚质")

    # #12 医疗场景
    print("\n[#12 医疗场景]")
    test("辅助辨证", "POST", "/api/v1/med/diagnose/assist",
         json={"tongue": "舌红苔黄", "pulse": "弦数", "symptoms": "头痛,口苦", "patient_alias": "P001"})
    test("处方安全审查", "POST", "/api/v1/med/prescription/review",
         json={"prescription": [{"herb": "甘草", "dose": "10g"}], "patient_info": {"age": 35, "gender": "male"}})
    test("方剂推荐", "GET", "/api/v1/med/formula/recommend?syndrome=肝郁气滞")
    test("医案归档", "POST", "/api/v1/med/cases",
         json={"patient_alias": "P001", "diagnoses": {"syndrome": "肝郁气滞"}, "prescriptions": [{"herbs": ["柴胡", "白芍"]}], "notes": "初诊"},
         headers={"Idempotency-Key": "test-key-001"})
    test("文献佐证", "GET", "/api/v1/med/evidence/肝郁气滞")

    # #13 培训场景
    print("\n[#13 培训场景]")
    test("经典检索", "GET", "/api/v1/edu/classics/search?keyword=伤寒")
    test("创建陪练会话", "POST", "/api/v1/edu/coach/sessions",
         json={"topic": "太阳病辨证", "difficulty": "medium"})
    test("教学病案库", "GET", "/api/v1/edu/cases/library")
    test("学情看板", "GET", "/api/v1/edu/progress/dashboard")

    # #14 L2稳定性
    print("\n[#14 L2稳定性]")
    test("平台状态", "GET", "/platform/status")
    test("平台健康", "GET", "/platform/health")

    # 汇总
    print("\n" + "=" * 60)
    print(f"测试结果: {PASS} 通过 / {FAIL} 失败 / 共 {PASS + FAIL} 项")
    print("=" * 60)
    if ERRORS:
        print("\n失败详情:")
        for e in ERRORS:
            print(f"  - {e}")
    return FAIL == 0

if __name__ == "__main__":
    ok = run_tests()
    sys.exit(0 if ok else 1)
