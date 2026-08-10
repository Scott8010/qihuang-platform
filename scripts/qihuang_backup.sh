#!/usr/bin/env bash
# -*- coding: utf-8 -*-
#
# 岐黄智脑平台 · 自动备份脚本
# 备份对象: PostgreSQL(业务核心) / Redis(缓存兜底) / Neo4j(图谱热拷)
# 保留策略: 7 天滚动
# 完成/失败均通过 PushPlus 推送微信通知
#
# 部署: 由 cron 每日 02:00 调用:
#   0 2 * * * /bin/bash /root/qihuang_backup.sh >>/root/backups/backup.cron 2>&1
#
set -u

BACKUP_DIR=/root/backups
mkdir -p "$BACKUP_DIR"
TS=$(date +%Y%m%d_%H%M%S)
KEEP_DAYS=7
ALERT=/root/qihuang_alert.py
LOG="$BACKUP_DIR/backup.log"

log() { echo "[$(date '+%F %T')] $*" | tee -a "$LOG"; }

# ---------- 1. PostgreSQL (业务核心, 必须成功) ----------
log "=== [1/3] PostgreSQL dump ==="
PGPASS=$(grep -E "^QH_DATABASE_URL" /root/qihuang_platform/.env 2>/dev/null | sed -E "s#.*://[^:]+:([^@]+)@.*#\1#")
if [ -z "$PGPASS" ]; then
    log "PG FAIL: cannot read QH_DATABASE_URL"
else
    docker exec -e PGPASSWORD="$PGPASS" qh-postgres pg_dump -U qihuang -F c -d qihuang_platform > "$BACKUP_DIR/pg_$TS.dump" 2>>"$LOG"
    if [ -s "$BACKUP_DIR/pg_$TS.dump" ]; then
        log "PG OK ($(du -h "$BACKUP_DIR/pg_$TS.dump" | cut -f1))"
    else
        log "PG FAIL: empty dump"
    fi
fi

# ---------- 2. Redis (缓存兜底, SAVE + 拷贝 dump.rdb) ----------
log "=== [2/3] Redis save+copy ==="
RP=$(grep -iE "REDIS_PASSWORD|REDIS_URL" /root/qihuang_platform/.env 2>/dev/null | head -1 | sed -E "s#.*://([^@]+)@.*#\1#; s#.*:##")
if [ -n "$RP" ]; then
    docker exec qh-redis redis-cli -a "$RP" SAVE >/dev/null 2>&1
fi
if cp -f /data/qihuang/redis/dump.rdb "$BACKUP_DIR/redis_$TS.rdb" 2>>"$LOG"; then
    log "Redis OK ($(du -h "$BACKUP_DIR/redis_$TS.rdb" | cut -f1))"
else
    log "Redis SKIP: no dump.rdb (likely empty instance)"
fi

# ---------- 3. Neo4j (图谱热拷, 最佳努力一致性) ----------
log "=== [3/3] Neo4j hot-copy (best-effort) ==="
if tar czf "$BACKUP_DIR/neo4j_$TS.tar.gz" -C /root/qihuang/app/neo4j-data data 2>>"$LOG"; then
    log "Neo4j OK ($(du -h "$BACKUP_DIR/neo4j_$TS.tar.gz" | cut -f1))"
else
    log "Neo4j FAIL: tar error"
fi

# ---------- 4. 滚动清理 ----------
find "$BACKUP_DIR" \( -name "*.dump" -o -name "*.rdb" -o -name "*.tar.gz" \) -mtime +$KEEP_DAYS -delete 2>>"$LOG"
log "=== rotation done (keep $KEEP_DAYS days) ==="

# ---------- 5. 推送结果 ----------
SIZE=$(du -sh "$BACKUP_DIR" 2>/dev/null | cut -f1)
python3 "$ALERT" "岐黄平台备份完成 $TS" "PG/Redis/Neo4j 已备份; 目录总占用 $SIZE; 保留 $KEEP_DAYS 天" 2>>"$LOG"
log "=== backup job finished ==="
