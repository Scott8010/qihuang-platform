"""活态化趋势采集 — 落首个快照（方案 2）

用法:
  # 生产环境（服务器可直连 8601）:
  python scripts/seed_living_snapshot.py
  # 本地验证（注入离线互考矩阵 JSON）:
  python scripts/seed_living_snapshot.py --quiz-json ../quiz_snapshot.json

建表由 init_db() 的 create_all 完成；本脚本仅负责写入第一条时间序列点。
"""
import argparse
import asyncio
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")  # 加载 .env（QH_DATABASE_URL / QH_KG_API_BASE 等）

from qihuang_platform.db.config import init_db
from qihuang_platform.living.trend import collect_living_snapshot


def main():
    ap = argparse.ArgumentParser(description="活态化趋势采集 - 落首个快照")
    ap.add_argument("--quiz-json", help="离线注入互考矩阵 JSON（本地验证用）")
    args = ap.parse_args()

    init_db()  # 确保 kg_confidence_snapshot 表存在
    res = asyncio.run(collect_living_snapshot(quiz_json_path=args.quiz_json))
    print("SEED RESULT:", res)


if __name__ == "__main__":
    main()
