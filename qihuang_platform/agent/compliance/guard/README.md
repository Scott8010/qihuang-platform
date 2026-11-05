# ⚠️ L0 规则引擎 —— 本目录是内容审核的命门，禁止删除

## 这是什么

本目录是 **8602 内容审核 AGENT 的 L0 硬红线规则引擎**（融合进 compliance 包的核心组件）：

| 文件 | 作用 |
|---|---|
| `rules.py` | 32 条内容合规规则（A~F 六大类），正则 + 免责语境豁免词 + 严重度 |
| `engine.py` | `scan_text()` 规则命中扫描 + `judge_state()` 四态判定 |

被 `qihuang_platform/agent/compliance/engine_l2.py` 的 `_find_rules_dir()` →
`os.path.join(_HERE, "guard")` **强引用**。

## 为什么单独立此 README

**2026-09-09 `79a7d8d` 曾把本目录当"误导入废目录"删除（478 行），导致：**

```
guard/ 不存在 → _load_l0() 抛 FileNotFoundError
    → analyze() 的 except 接住 → l0_hits=[] → judge([]) → "已通过"
    → 【所有违规内容一律放行，API 返回 code=0、看板正常、无人知情】
```

**静默失效 56 天**（2026-09-09 12:29 → 2026-11-04 23:17）。生产因"CI 恰好一直红、
部署停摆、且 rsync 不带 --delete"四重巧合而侥幸未受影响——但这不等于安全。

完整复盘见：`01_项目文档/岐黄智脑/8602内容审核_L0失效事件完整复盘_2026-11-04.md`

## 删除前必做的核查

```bash
# 1. 谁在引用？（必须有输出，有输出就不许删）
grep -rn "compliance/guard\|_find_rules_dir\|RULES_DIR" --include="*.py" qihuang_platform/ tests/

# 2. 引用链核心在 engine_l2.py 的 _load_l0()
# 3. 跑一次自检（必须 ok=true）
python3 -c "from qihuang_platform.agent.compliance.engine_l2 import verify_l0; print(verify_l0())"
# 期望: {'ok': True, 'rule_count': 32, 'sample_state': '违规拦截', ...}
```

若自检 `ok=false`，说明规则已失效，**内容审核处于全放行状态**，必须立即修复。

## 已就位的防复发守卫（2026-11-04 起）

| 守卫 | 位置 | 行为 |
|---|---|---|
| 启动自检 | `main.py` lifespan | 失败打 ERROR；`QH_COMPLIANCE_STRICT=1` 时拒绝启动 |
| 健康检查 | `/platform/health` → `compliance_l0` | `ok=false` 时顶层 `status=degraded` |
| 监控大盘 | `/admin/v1/monitor/overview` → `compliance_l0` | 自动生成 `critical` 告警 |
| 守卫测试 | `tests/test_agent_compliance.py` | `test_l0_engine_loadable` 等，CI 立即红 |

## 与已删除的独立 hb-compliance-guard 的区别（关键，别搞混）

| | 本目录 `8602/agent/compliance/guard/` | `HealthBridge/hb-compliance-guard/` |
|---|---|---|
| 性质 | ✅ **8602 融合后的 L0 引擎（必需，保留）** | ❌ 独立的旧 HTTP 服务（已废弃，已删） |
| 形态 | 包内模块，被 engine_l2 直接加载 | 独立服务，早期通过 HTTP 调用 |
| 处置 | **禁止删除** | 已于 2026-09-08 清除为冗余 |

> 名字里都有 "guard"，但一个是"融合后的器官"，一个是"切掉的旧器官"。删错就会重演 56 天静默失效。
