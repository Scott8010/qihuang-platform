"""pytest 根配置：把项目根加入 sys.path，保证内部 qihuang_platform 包可导入。

注意：项目根目录自身也有 __init__.py（与内部 qihuang_platform/ 子包同名），
而 pytest 启动时会把项目根的「父目录」插入 sys.path[0]，导致 `import qihuang_platform`
优先命中根目录那个同名空包（不含 agent）。这里：① 把项目根置顶；② 移除父目录，
使 `import qihuang_platform` 解析到内层真正带 agent/compliance 的包。
"""
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
PARENT = os.path.dirname(ROOT)

if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
if PARENT in sys.path:
    sys.path.remove(PARENT)
