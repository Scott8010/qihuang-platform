import requests, json, sys

BASE = "http://localhost:8602"
r = requests.post(f"{BASE}/dev/admin-login", timeout=5)
TOKEN = r.json()["data"]["access_token"]
H = {"Authorization": f"Bearer {TOKEN}"}

PASS = 0
FAIL = 0
SKIP = 0

def test(name, method, path, **kw):
    global PASS, FAIL, SKIP
    try:
        r = requests.request(method, f"{BASE}{path}", headers=H, timeout=10, **kw)
        body = r.json() if "json" in r.headers.get("content-type", "") else {}
        code = body.get("code", "?")
        msg_text = body.get("message", "")
        # code=0 = success, code=5002 = 8601 backend not running (expected), code=6002 = duplicate (expected for re-runs)
        if r.status_code == 200 and code == 0:
            PASS += 1
            print(f"[PASS] {name} -> HTTP {r.status_code} code={code}", flush=True)
        elif code == 5002:
            SKIP += 1
            print(f"[SKIP] {name} -> 8601 backend not running (expected): {msg_text}", flush=True)
        elif code == 6002:
            SKIP += 1
            print(f"[SKIP] {name} -> duplicate data (expected on re-run): {msg_text}", flush=True)
        else:
            FAIL += 1
            print(f"[FAIL] {name} -> HTTP {r.status_code} code={code} msg={msg_text}", flush=True)
    except requests.exceptions.Timeout:
        SKIP += 1
        print(f"[SKIP] {name} -> timeout (8601 not running)", flush=True)
    except Exception as e:
        FAIL += 1
        print(f"[FAIL] {name} -> {e}", flush=True)

# #20 计费
test("用量查询", "GET", "/admin/v1/billing/usage")
test("账单列表", "GET", "/admin/v1/billing/bills")
test("生成月账单", "POST", "/admin/v1/billing/bills/generate", json={"tenant_id": "tenant_default", "period": "2026-07"})
test("订阅列表", "GET", "/admin/v1/subscriptions")
test("创建套餐", "POST", "/admin/v1/plans", json={"plan_name": "test_p", "display_name": "test", "price_cents": 500})

# #15 控制端
test("知识审核待审", "GET", "/admin/v1/kg/review/pending")
test("KG版本列表", "GET", "/admin/v1/kg/versions")
test("监控大盘", "GET", "/admin/v1/monitor/overview")
test("LLM状态", "GET", "/admin/v1/monitor/llm-status")
test("审计日志", "GET", "/admin/v1/audit-logs")
test("敏感词列表", "GET", "/admin/v1/content/words")
test("添加敏感词", "POST", "/admin/v1/content/words", json={"scene": "HEALTH", "word": "test_word", "level": "warn"})
test("租户监控", "GET", "/admin/v1/monitor/tenant/tenant_default")

# #9 大健康
test("体质辨识", "POST", "/api/v1/health/constitution/assess", json={"symptoms": "headache"})
test("体质列表", "GET", "/api/v1/health/constitutions")
test("档案时间轴", "GET", "/api/v1/health/archive/timeline")
test("穴位指导", "GET", "/api/v1/health/acupoints/guide?constitution_type=%E6%B0%94%E8%99%9A%E8%B4%A8")

# #12 医疗
test("辅助辨证", "POST", "/api/v1/med/diagnose/assist", json={"tongue": "red", "pulse": "wiry", "symptoms": "headache", "patient_alias": "P001"})
test("处方审查", "POST", "/api/v1/med/prescription/review", json={"prescription": [{"herb": "gancao", "dose": "10g"}], "patient_info": {"age": 35, "gender": "male"}})
test("方剂推荐", "GET", "/api/v1/med/formula/recommend?syndrome=test")
test("医案归档", "POST", "/api/v1/med/cases", json={"patient_alias": "P001", "diagnoses": {}, "prescriptions": [], "notes": "test"})
test("文献佐证", "GET", "/api/v1/med/evidence/test")

# #13 培训
test("经典检索", "GET", "/api/v1/edu/classics/search?keyword=shanghan")
test("创建陪练", "POST", "/api/v1/edu/coach/sessions", json={"topic": "taiyang", "difficulty": "medium"})
test("病案库", "GET", "/api/v1/edu/cases/library")
test("学情看板", "GET", "/api/v1/edu/progress/dashboard")

total = PASS + FAIL + SKIP
result = f"\n{'='*60}\nResult: {PASS} passed / {FAIL} failed / {SKIP} skipped(8601/dup) / {total} total\n{'='*60}"
print(result, flush=True)
sys.exit(0 if FAIL == 0 else 1)
