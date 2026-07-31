"""
岐黄智脑 - 3D穴位数据模块

独立穴位/经络数据层，从 model/opensource/ 抽离为结构化 API 下发。
子任务1: 数据剥离 - 穴位三维坐标与经络循行路径为独立JSON数据包
子任务5: 3个新core端点 - model/guide/meridians

数据源: model/opensource/opensource_acupoints.json (MIT license)
"""
from .data import AcupointData, acupoint_data

__all__ = ["AcupointData", "acupoint_data"]
