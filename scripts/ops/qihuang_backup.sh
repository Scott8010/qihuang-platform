#!/usr/bin/env bash
# -*- coding: utf-8 -*-
#
# 岐黄智脑平台 · 自动备份脚本 (生产加固版 v2)
# ============================================================
# 备份对象:
#   1) PostgreSQL 业务库 (qihuang_platform)  —— 自定义格式 dump
#   2) Redis dump.rdb (缓存兜底)
#   3) Neo4j 图谱热拷 (tar 一致性最佳努力)
#   4) 配置 .env (qihuang_platform/.env + qihuang/app/.env) —— 可还原密钥/增益开关
# 保留策略: 7 天滚动
# 完整性校验:
#   PG    -> docker cp 进容器跑 pg_restore -l 验证自定义格式归档
#   Redis -> RDB 魔数 "REDIS" 校验
#   Neo4j -> tar -tzf 校验 gzip+tar 完整性
#   ENV   -> 文件存在且非空
# 告警策略 (核心修复 P0-1):
#   任一组件失败/告警 -> 标题标 ⚠️, 内容逐项列出真实状态
#   仅当 4/4 全部成功才报 "✅ 备份完成"
#   (旧版无条件推送"已完成"属于假阳性, 监控已失效)
#
# 部署: cron 每日 02:00
#   0 2 * * * /bin/bash /root/qihuang_backup.sh >>/root/backups/backup.cron 2>&1
#
set -u

BACKUP_DIR=/root/backups
mkdir -p "$BACKUP_DIR"
TS=$(date +%Y%m%d_%H%M%S)
KEEP_DAYS=7
ALERT=/root/qihuang_alert.py
LOG="$BACKUP_DIR/backup.log"

# 组件状态 1=OK 0=FAIL / 明细
PG_OK=0;    PG_DETAIL=""
REDIS_OK=0; REDIS_DETAIL=""
NEO4J_OK=0; NEO4J_DETAIL=""
ENV_OK=0;   ENV_DETAIL=""

log() { echo "[$(date '+%F %T')] $*" | tee -a "$LOG"; }

# ---------- 1. PostgreSQL (业务核心, 必须成功+校验) ----------
log "=== [1/4] PostgreSQL dump ==="
PGPASS=$(grep -E "^QH_DATABASE_URL" /root/qihuang_platform/.env 2>/dev/null | sed -E "s#.*://[^:]+:([^@]+)@.*#\1#")
if [ -z "$PGPASS" ]; then
    PG_DETAIL="FAIL: 无法读取 QH_DATABASE_URL 密码"
else
    if docker exec -e PGPASSWORD="$PGPASS" qh-postgres pg_dump -U qihuang -F c -d qihuang_platform > "$BACKUP_DIR/pg_$TS.dump" 2>>"$LOG"; then
        if [ -s "$BACKUP_DIR/pg_$TS.dump" ]; then
            # 完整性校验: 自定义格式归档可列出 (= 可还原的前提)
            docker cp "$BACKUP_DIR/pg_$TS.dump" qh-postgres:/tmp/_pgverify_$TS.dump >/dev/null 2>&1
            if docker exec qh-postgres pg_restore -l -F c /tmp/_pgverify_$TS.dump >/dev/null 2>&1; then
                PG_OK=1
                PG_DETAIL="OK ($(du -h "$BACKUP_DIR/pg_$TS.dump" | cut -f1), pg_restore -l 校验通过)"
            else
                PG_DETAIL="WARN: dump 非空但 pg_restore -l 校验失败"
            fi
            docker exec qh-postgres rm -f /tmp/_pgverify_$TS.dump >/dev/null 2>&1
        else
            PG_DETAIL="FAIL: 空 dump"
        fi
    else
        PG_DETAIL="FAIL: pg_dump 执行错误 (容器/网络/密码)"
    fi
fi
log "PG -> $PG_DETAIL"

# ---------- 2. Redis (缓存兜底, SAVE + 拷贝 dump.rdb) ----------
log "=== [2/4] Redis save+copy ==="
RP=$(grep -iE "REDIS_PASSWORD|REDIS_URL" /root/qihuang_platform/.env 2>/dev/null | head -1 | sed -E "s#.*://([^@]+)@.*#\1#; s#.*:##")
if [ -n "$RP" ]; then
    docker exec qh-redis redis-cli -a "$RP" SAVE >/dev/null 2>&1
fi
if cp -f /data/qihuang/redis/dump.rdb "$BACKUP_DIR/redis_$TS.rdb" 2>>"$LOG"; then
    if [ -s "$BACKUP_DIR/redis_$TS.rdb" ]; then
        if head -c 5 "$BACKUP_DIR/redis_$TS.rdb" | grep -q "REDIS"; then
            REDIS_OK=1
            REDIS_DETAIL="OK ($(du -h "$BACKUP_DIR/redis_$TS.rdb" | cut -f1), RDB 魔数校验通过)"
        else
            REDIS_DETAIL="WARN: 非空但 RDB 魔数校验失败"
        fi
    else
        REDIS_DETAIL="FAIL: 空 dump.rdb"
    fi
else
    REDIS_DETAIL="FAIL: cp dump.rdb 失败 (源不存在/权限)"
fi
log "Redis -> $REDIS_DETAIL"

# ---------- 3. Neo4j (图谱热拷, 最佳努力一致性) ----------
log "=== [3/4] Neo4j hot-copy (best-effort) ==="
if tar czf "$BACKUP_DIR/neo4j_$TS.tar.gz" -C /root/qihuang/app/neo4j-data data 2>>"$LOG"; then
    if [ -s "$BACKUP_DIR/neo4j_$TS.tar.gz" ]; then
        if tar -tzf "$BACKUP_DIR/neo4j_$TS.tar.gz" >/dev/null 2>&1; then
            NEO4J_OK=1
            NEO4J_DETAIL="OK ($(du -h "$BACKUP_DIR/neo4j_$TS.tar.gz" | cut -f1), tar -tzf 校验通过)"
        else
            NEO4J_DETAIL="WARN: 非空但 tar -tzf 校验失败"
        fi
    else
        NEO4J_DETAIL="FAIL: 空 tar"
    fi
else
    NEO4J_DETAIL="FAIL: tar 错误"
fi
log "Neo4j -> $NEO4J_DETAIL"

# ---------- 4. 配置 .env (可还原密钥/增益开关, 修复 P0-2) ----------
log "=== [4/4] 配置 .env 备份 ==="
ENV_COUNT=0
declare -a ENV_SRCS=("/root/qihuang_platform/.env" "/root/qihuang/app/.env")
declare -a ENV_TAGS=("qihuang_platform" "qihuang_app")
for i in 0 1; do
    f="${ENV_SRCS[$i]}"; tag="${ENV_TAGS[$i]}"
    if [ -f "$f" ]; then
        if cp -f "$f" "$BACKUP_DIR/${tag}.env_$TS" 2>>"$LOG"; then
            ENV_COUNT=$((ENV_COUNT + 1))
        else
            ENV_DETAIL="$ENV_DETAIL | $tag:cp 失败"
        fi
    else
        ENV_DETAIL="$ENV_DETAIL | $tag:缺失"
    fi
done
# ENV 作为单个组件: 仅当 2/2 全部成功才算 OK, 否则 FAIL/WARN (总数保持 4 分量)
if [ "$ENV_COUNT" -eq 2 ]; then
    ENV_OK=1
    ENV_DETAIL="OK (备份 2 个: qihuang_platform.env_$TS, qihuang_app.env_$TS)"
elif [ "$ENV_COUNT" -ge 1 ]; then
    ENV_DETAIL="WARN: 部分成功($ENV_COUNT/2) $ENV_DETAIL"
else
    ENV_DETAIL="FAIL: 全部失败 $ENV_DETAIL"
fi
log "ENV -> $ENV_DETAIL"

# ---------- 5. 滚动清理 (7 天) ----------
find "$BACKUP_DIR" \( -name "*.dump" -o -name "*.rdb" -o -name "*.tar.gz" -o -name "*.env_*" \) -mtime +$KEEP_DAYS -delete 2>>"$LOG"
log "=== rotation done (keep $KEEP_DAYS days) ==="

# ---------- 6. 汇总推送 (真实状态, 不谎报) ----------
SIZE=$(du -sh "$BACKUP_DIR" 2>/dev/null | cut -f1)
TOTAL=$((PG_OK + REDIS_OK + NEO4J_OK + ENV_OK))
if [ "$TOTAL" -eq 4 ]; then
    TITLE="✅ 岐黄平台备份完成 $TS"
    CONTENT="PG/Redis/Neo4j/配置 全部成功 (4/4); 目录总占用 $SIZE; 保留 $KEEP_DAYS 天"
else
    TITLE="⚠️ 岐黄平台备份异常 $TS"
    CONTENT="成功 $TOTAL/4。明细 => [PG] $PG_DETAIL | [Redis] $REDIS_DETAIL | [Neo4j] $NEO4J_DETAIL | [配置] $ENV_DETAIL ; 目录总占用 $SIZE"
fi
python3 "$ALERT" "$TITLE" "$CONTENT" 2>>"$LOG"
log "=== backup job finished (ok=$TOTAL/4) ==="
exit 0
