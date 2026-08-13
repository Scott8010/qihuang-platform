"""命理运程 Agent · 请求/响应 Schema。"""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class ArchiveRequest(BaseModel):
    user_id: str = Field(..., description="用户标识（钉业务实体主键）")
    pillars: str = Field(..., description="四柱，空格分隔：年柱 月柱 日柱 时柱，如 '庚申 丙戌 丁巳 辛丑'")
    name: Optional[str] = Field(None, description="昵称/备注")
    persist: bool = Field(True, description="是否真实入库")


class CastRequest(BaseModel):
    method: str = Field("coin", description="起卦方式：coin 铜钱 / time 时间")
    question: Optional[str] = Field(None, description="所问之事（仅记录，不参与算法）")
    user_id: Optional[str] = Field(None, description="可选，用于回写个人档案")


class DailyRequest(BaseModel):
    user_id: Optional[str] = Field(None, description="可选，带入个人喜用神做个性化")
    pillars: Optional[str] = Field(None, description="可选，四柱用于个性化喜用")


class ReportRequest(BaseModel):
    user_id: Optional[str] = Field(None, description="已建档用户标识")
    pillars: Optional[str] = Field(None, description="未建档时直接给四柱")
    year: Optional[int] = Field(None, description="默认今年")
