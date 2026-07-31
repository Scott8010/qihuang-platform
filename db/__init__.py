"""
PostgreSQL ORM模型 — Phase 1 (#10)

24张表分4域，全雪花ID主键，AES-256-GCM加密敏感字段：
  账号权限域(7): tenant / org / user / role / permission / user_role / role_permission
  计费计量域(6): plan / subscription / api_key / call_log / bill / audit_log
  业务数据域(9): med_case / med_report / health_profile / health_assessment /
                  health_plan / health_event / edu_coach_session / edu_exam_record / upload_file
  内容管控域(3): sensitive_word / kg_review_item / kg_version

铁律：
  - tenant_id行级隔离（所有查询必须带）
  - 雪花ID主键（snowflake_id）
  - 敏感字段AES-256-GCM加密
  - 禁止外键，应用层保证一致性
"""
