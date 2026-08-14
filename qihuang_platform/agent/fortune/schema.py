"""命理运程 Agent · 请求/响应 Schema。"""
from __future__ import annotations

from typing import Union, Optional

from pydantic import BaseModel, Field


class ArchiveRequest(BaseModel):
    user_id: str = Field(..., description="用户标识（钉业务实体主键）")
    pillars: Optional[str] = Field(None, description="四柱，空格分隔：年柱 月柱 日柱 时柱，如 '庚申 丙戌 丁巳 辛丑'；与 birth 二选一")
    birth: Optional[dict] = Field(None, description="公历生日建档：{'date':'YYYY-MM-DD','hour':0-23}；与 pillars 二选一")
    name: Optional[str] = Field(None, description="昵称/备注")
    gender: Optional[str] = Field(None, description="性别：男 / 女（大运顺逆排所需）")
    persist: bool = Field(True, description="是否真实入库")


class CastRequest(BaseModel):
    method: str = Field("coin", description="起卦方式：coin 铜钱 / time 时间")
    question: Optional[str] = Field(None, description="所问之事（仅记录，不参与算法）")
    ai: bool = Field(False, description="是否启用 LLM 象义层（AI 详批散文，需平台配置 FORTUNE_LLM_*）")
    user_id: Optional[str] = Field(None, description="可选，用于回写个人档案")


class DailyRequest(BaseModel):
    user_id: Optional[str] = Field(None, description="可选，带入个人喜用神做个性化")
    pillars: Optional[str] = Field(None, description="可选，四柱用于个性化喜用")
    ai: bool = Field(False, description="是否启用 LLM 象义层（AI 散文详批，需平台配置 FORTUNE_LLM_*）")


class ReportRequest(BaseModel):
    user_id: Optional[str] = Field(None, description="已建档用户标识")
    pillars: Optional[str] = Field(None, description="未建档时直接给四柱")
    gender: Optional[str] = Field(None, description="性别：男 / 女（大运所需）")
    year: Optional[int] = Field(None, description="默认今年")
    ai: bool = Field(False, description="是否启用 LLM 象义层（AI 散文详批，需平台配置 FORTUNE_LLM_*）")


class GeoRequest(BaseModel):
    orientation: Union[dict, str] = Field(
        ..., description=(
            "坐向（堪舆必填）："
            "罗盘度数 {'facing_deg': 178.3, 'source': 'device'} / "
            "24山 {'sitting': '子', 'facing': '午'} / "
            "'子山午向' / '坐北朝南'"
        ))
    gps: Optional[dict] = Field(
        None, description="定位 {'lat': 31.23, 'lon': 121.47, 'year': 2026}，用于磁偏角校正+外部峦头占位")
    floor_plan: Optional[Union[dict, str]] = Field(
        None, description=(
            "户型/实地信息。结构化(dict)优先，字段中文键："
            "{'门向':'南','主卧方':'东南','厨房方':'东','卫生间方':'西北',"
            "'缺角':['西南'],'横梁':false,'穿堂':false}；"
            "或传图片URL/备注字符串（多模态视觉解析另走视觉通道，当前为占位钩子）。"
        ))
    user_id: Optional[str] = Field(None, description="可选，回写个人档案")
