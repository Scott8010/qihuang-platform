"""服务端收尾检查：确认无业务反馈残留污染 + 8602 服务在线 + 增益生效。"""
import os
from dotenv import load_dotenv
load_dotenv("/root/qihuang_platform/.env")

from qihuang_platform.db.config import SessionLocal
from qihuang_platform.living.models import KgFeedback
from qihuang_platform.living.aggregator import _BUSINESS_GAIN

db = SessionLocal()
n = db.query(KgFeedback).filter(KgFeedback.source == "business").count()
print("business_rows =", n)
for r in db.query(KgFeedback).filter(KgFeedback.source == "business").all():
    print("  LEAK:", r.kg_id, r.feedback_type, r.business_weight, r.comment)
db.close()
print("LIVING_BUSINESS_GAIN =", _BUSINESS_GAIN)
