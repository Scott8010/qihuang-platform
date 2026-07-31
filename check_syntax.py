import sys, os
os.chdir(r"C:\Users\Administrator\Desktop\岐黄大脑\平台开发\qihuang_platform")
sys.path.insert(0, ".")

files = [
    "qihuang_platform/billing/billing.py",
    "qihuang_platform/billing/quota.py",
    "qihuang_platform/capability/routers/health.py",
    "qihuang_platform/capability/routers/education.py",
    "qihuang_platform/gateway/llm_fallback.py",
    "qihuang_platform/gateway/monitor.py",
    "qihuang_platform/control/router.py",
]

for f in files:
    try:
        with open(f, "r", encoding="utf-8") as fh:
            code = fh.read()
        compile(code, f, "exec")
        print(f"[OK] {f}")
    except SyntaxError as e:
        print(f"[ERR] {f}: line {e.lineno}: {e.msg}")
    except Exception as e:
        print(f"[ERR] {f}: {e}")
