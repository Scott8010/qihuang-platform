#!/usr/bin/env bash
# -*- coding: utf-8 -*-
#
# 岐黄智脑平台 · 备份可还原验证 (一次性 restore proof)
# ============================================================
# 目的: 证明 /root/backups 中的最新备份确实可还原 (不能还原=没备份)
#   PG    -> 还原到临时库 qihuang_restore_test, 校验表数量>0, 用完即删
#   Redis -> docker cp 进容器跑 redis-check-rdb 校验 RDB 完整性
#   Neo4j -> 解包 tar 到临时目录, 校验 data/databases 结构存在
# 仅读备份、不改生产数据; 失败明确报错并退出码非零
#
set -u

BACKUP_DIR=/root/backups
LOG=/root/backups/restore_test.log
PG_DB_TEST=qihuang_restore_test

log() { echo "[$(date '+%F %T')] $*" | tee -a "$LOG"; }
PASS=0; FAIL=0

# 取最新各组件备份
LATEST_PG=$(ls -1t "$BACKUP_DIR"/pg_*.dump 2>/dev/null | head -1)
LATEST_REDIS=$(ls -1t "$BACKUP_DIR"/redis_*.rdb 2>/dev/null | head -1)
LATEST_NEO4J=$(ls -1t "$BACKUP_DIR"/neo4j_*.tar.gz 2>/dev/null | head -1)

log "=== 备份可还原验证启动 ==="

# ---------- PG ----------
if [ -z "$LATEST_PG" ]; then
    log "PG FAIL: 无 pg_*.dump"; FAIL=$((FAIL+1))
else
    PGPASS=$(grep -E "^QH_DATABASE_URL" /root/qihuang_platform/.env 2>/dev/null | sed -E "s#.*://[^:]+:([^@]+)@.*#\1#")
    log "PG 还原测试 -> $LATEST_PG"
    docker exec -e PGPASSWORD="$PGPASS" qh-postgres dropdb --if-exists -U qihuang "$PG_DB_TEST" >/dev/null 2>&1
    if docker exec -e PGPASSWORD="$PGPASS" qh-postgres createdb -U qihuang "$PG_DB_TEST" 2>>"$LOG"; then
        # 容器内无 /root/backups 挂载, 需先 docker cp 进容器再还原
        docker cp "$LATEST_PG" qh-postgres:/tmp/_pgrestore_$$.dump >/dev/null 2>&1
        if docker exec -e PGPASSWORD="$PGPASS" qh-postgres pg_restore -U qihuang -d "$PG_DB_TEST" /tmp/_pgrestore_$$.dump >/dev/null 2>>"$LOG"; then
            TBL=$(docker exec -e PGPASSWORD="$PGPASS" qh-postgres psql -t -U qihuang -d "$PG_DB_TEST" -c "SELECT count(*) FROM information_schema.tables WHERE table_schema NOT IN ('pg_catalog','information_schema');" 2>/dev/null | tr -d ' ')
            if [ "${TBL:-0}" -gt 0 ]; then
                log "PG OK: 还原成功, 业务表数=$TBL"; PASS=$((PASS+1))
            else
                log "PG FAIL: 还原后无业务表"; FAIL=$((FAIL+1))
            fi
        else
            log "PG FAIL: pg_restore 执行错误"; FAIL=$((FAIL+1))
        fi
        docker exec qh-postgres rm -f /tmp/_pgrestore_$$.dump >/dev/null 2>&1
        docker exec -e PGPASSWORD="$PGPASS" qh-postgres dropdb --if-exists -U qihuang "$PG_DB_TEST" >/dev/null 2>&1
    else
        log "PG FAIL: 无法创建临时库"; FAIL=$((FAIL+1))
    fi
fi

# ---------- Redis ----------
if [ -z "$LATEST_REDIS" ]; then
    log "Redis FAIL: 无 redis_*.rdb"; FAIL=$((FAIL+1))
else
    log "Redis 校验 -> $LATEST_REDIS"
    docker cp "$LATEST_REDIS" qh-redis:/tmp/_rdbcheck.rdb >/dev/null 2>&1
    if docker exec qh-redis redis-check-rdb /tmp/_rdbcheck.rdb 2>/dev/null | grep -q "CRC64\|0 errors\|ok"; then
        log "Redis OK: redis-check-rdb 通过"; PASS=$((PASS+1))
    else
        log "Redis FAIL: redis-check-rdb 未通过"; FAIL=$((FAIL+1))
    fi
    docker exec qh-redis rm -f /tmp/_rdbcheck.rdb >/dev/null 2>&1
fi

# ---------- Neo4j ----------
if [ -z "$LATEST_NEO4J" ]; then
    log "Neo4j FAIL: 无 neo4j_*.tar.gz"; FAIL=$((FAIL+1))
else
    log "Neo4j 解包校验 -> $LATEST_NEO4J"
    TMP=/tmp/neo4j_restore_test_$$
    rm -rf "$TMP"; mkdir -p "$TMP"
    if tar xzf "$LATEST_NEO4J" -C "$TMP" 2>>"$LOG" && [ -d "$TMP/data/databases" ]; then
        DBCOUNT=$(ls -1 "$TMP/data/databases" 2>/dev/null | wc -l)
        log "Neo4j OK: 解包成功, databases 数=$DBCOUNT"; PASS=$((PASS+1))
    else
        log "Neo4j FAIL: 解包或结构校验失败"; FAIL=$((FAIL+1))
    fi
    rm -rf "$TMP"
fi

log "=== 验证结束: PASS=$PASS FAIL=$FAIL ==="
[ "$FAIL" -eq 0 ] && exit 0 || exit 1
