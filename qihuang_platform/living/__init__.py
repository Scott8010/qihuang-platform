"""活态化反馈闭环包（P2）

让 8602 侧采集的用户/专家反馈，通过聚合计算后回写 8601 的 /kg/api 写通道，
使知识图谱 confidence 随真实使用演化（回路一：反馈→置信度；回路二：专家纠偏；
回路四：知识缺口标记）。

设计依据：岐黄智脑活态化改造 P1 详细设计 第五节（confidence 批量回写算法）。
"""
from qihuang_platform.living.router import router
from qihuang_platform.living.scheduler import start_living_scheduler

__all__ = ["router", "start_living_scheduler"]
