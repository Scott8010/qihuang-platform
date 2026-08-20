"""
crawler HTTP 触发端点（需求7 图谱治理 Stage B 触发入口）

运营台 / 自动化任务可经此端点触发摄入管线：POST /admin/v1/crawler/run
  - source_key：SOURCES 注册表键（static-demo / tcm-encyclopedia / ...）
  - allow_network：真实抓取需 True（默认 False，HttpPageAdapter 不联网）
  - dry_run：仅分类统计、不落库（默认 False）
  - min_confidence / reviewer_role：分类阈值与审核角色

返回与网关统一响应同构：{code, message, data}，data 含 total/ingested/skipped/by_type/ids/persisted。
"""
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .pipeline import run_crawl

crawler_router = APIRouter()


class CrawlRequest(BaseModel):
    source_key: str
    limit: Optional[int] = None
    allow_network: bool = False
    dry_run: bool = False
    reviewer_role: str = "XZ"
    min_confidence: float = 0.2


class CrawlResponse(BaseModel):
    code: int = 0
    message: str = "ok"
    data: dict = {}


@crawler_router.post("/admin/v1/crawler/run")
def crawler_run(req: CrawlRequest):
    """触发一次知识图谱摄入（分类 → 落 KgReviewItem 审核队列）。"""
    try:
        rep = run_crawl(
            source_key=req.source_key,
            limit=req.limit,
            allow_network=req.allow_network,
            reviewer_role=req.reviewer_role,
            min_confidence=req.min_confidence,
            commit=not req.dry_run,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail={"code": 400, "message": str(e)})

    data = rep.to_dict()
    if req.dry_run:
        data["persisted"] = False
        data["ids"] = []
        return CrawlResponse(message="dry_run 完成，未落库", data=data)
    data["persisted"] = True
    return CrawlResponse(data=data)
