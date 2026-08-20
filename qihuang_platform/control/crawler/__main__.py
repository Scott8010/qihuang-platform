"""
crawler CLI · python -m qihuang_platform.control.crawler

示例：
  python -m qihuang_platform.control.crawler --source static-demo --limit 10
  python -m qihuang_platform.control.crawler --source tcm-encyclopedia --allow-network
"""
import argparse
import json

from .pipeline import run_crawl
from .sources import list_sources


def main():
    ap = argparse.ArgumentParser(description="岐黄知识图谱摄入爬虫")
    ap.add_argument("--source", default="static-demo", help=f"数据源键（可用: {', '.join(list_sources())}）")
    ap.add_argument("--limit", type=int, default=None, help="最大摄入条数")
    ap.add_argument("--allow-network", action="store_true", help="允许真实外网抓取（默认关闭）")
    ap.add_argument("--dry-run", action="store_true", help="仅分类统计、不落库（默认落库）")
    ap.add_argument("--reviewer-role", default="XZ", help="审核角色 DZ/XZ")
    args = ap.parse_args()

    print(f"[crawler] 数据源={args.source} allow_network={args.allow_network} dry_run={args.dry_run}")
    rep = run_crawl(
        args.source,
        limit=args.limit,
        allow_network=args.allow_network,
        reviewer_role=args.reviewer_role,
        commit=not args.dry_run,
    )
    print(json.dumps(rep.to_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
