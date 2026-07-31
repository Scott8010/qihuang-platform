import sys, os
os.chdir(r"C:\Users\Administrator\Desktop\岐黄大脑\平台开发\qihuang_platform")
sys.path.insert(0, ".")

f = "qihuang_platform/capability/routers/medical.py"
try:
    with open(f, "r", encoding="utf-8") as fh:
        code = fh.read()
    compile(code, f, "exec")
    print(f"[OK] {f} ({len(code)} bytes)")
except SyntaxError as e:
    print(f"[ERR] {f}: line {e.lineno}: {e.msg}")
except Exception as e:
    print(f"[ERR] {f}: {e}")
