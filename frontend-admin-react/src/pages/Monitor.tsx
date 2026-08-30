import { useEffect, useState } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Cpu, ScrollText, CheckCircle2, AlertTriangle } from "lucide-react";
import { C } from "@/lib/types";
import { fetchServices, fetchLlmProviders, fetchAuditLogs } from "@/lib/api";
import { fmtDateTime } from "@/lib/format";
import type { ServiceItem, LlmProviderItem, AuditLogItem } from "@/lib/types";

/* 全量真实数据驱动：
   - 服务健康 → GET /admin/v1/monitor/services
   - 审计日志 → GET /admin/v1/audit-logs
   - LLM 分模型计量：后端暂无端点，返回空 → 显示诚实空态（不再回落 mock） */

/** 审计动作枚举 -> 中文标签。未命中映射则原样显示。 */
const AUDIT_ACTION_LABELS: Record<string, string> = {
  TENANT_ONBOARD: "租户入驻",
  CREATE_TENANT: "创建租户",
  DELETE_TENANT: "删除租户",
  ORG_CREATE: "创建机构",
  USER_CREATE: "创建用户",
  USER_DISABLE: "停用用户",
  ROLE_GRANT: "授予角色",
  ROLE_REVOKE: "撤销角色",
  API_KEY_CREATE: "签发 API Key",
  API_KEY_ROTATE: "API Key 轮换",
  API_KEY_REVOKE: "API Key 吊销",
  KEY_READONLY: "Key 进入只读",
  PLAN_CHANGE: "套餐变更",
  PLAN_UPGRADE: "套餐升级",
  PLAN_DOWNGRADE: "套餐降级",
  KG_REVIEW_APPROVED: "图谱审核通过",
  KG_REVIEW_REJECTED: "图谱审核驳回",
  KG_REVIEW_PENDING: "图谱审核转审",
  COMPLIANCE_BLOCK: "合规拦截",
  CONTENT_DELETE: "内容下架",
  CONTENT_EDIT: "内容编辑",
};
function labelOfAction(raw: string): string {
  if (!raw) return "—";
  return AUDIT_ACTION_LABELS[raw] || AUDIT_ACTION_LABELS[String(raw).toUpperCase()] || raw;
}
/** 动作语义分类 -> 颜色（success=通过、info=新建、warn=变更/轮换、danger=驳回/吊销）。 */
function toneOfAction(raw: string): "success" | "info" | "warn" | "danger" | "neutral" {
  const r = String(raw || "").toUpperCase();
  if (/REJECT|FAIL|DISABLE|BLOCK|REVOKE|DELETE|REJECTED/.test(r)) return "danger";
  if (/CREATE|GENERATE|REGISTER|ADD|ONBOARD/.test(r)) return "info";
  if (/APPROVE|GRANT|ENABLE|PASS/.test(r)) return "success";
  if (/ROTATE|READONLY|PENDING|UPDATE|CHANGE|UPGRADE|DOWNGRADE|EDIT/.test(r)) return "warn";
  return "neutral";
}
const TONE_CLASS = {
  success: "bg-emerald-50 text-emerald-700 border-emerald-200",
  info:    "bg-sky-50 text-sky-700 border-sky-200",
  warn:    "bg-amber-50 text-amber-700 border-amber-200",
  danger:  "bg-rose-50 text-rose-700 border-rose-200",
  neutral: "bg-gray-50 text-gray-600 border-gray-200",
} as const;
/** 由 action 推导对象类型中文名（用于对象列「类型 #序号」展示）。 */
function kindOfAction(raw: string): string {
  const r = String(raw || "").toUpperCase();
  if (r.includes("KG_REVIEW") || r.startsWith("KG_")) return "图谱审核单";
  if (r.includes("TENANT")) return "租户";
  if (r.includes("API_KEY") || r.includes("KEY") || r.includes("KEY_READONLY")) return "API Key";
  if (r.includes("ORG")) return "机构";
  if (r.includes("USER")) return "用户";
  if (r.includes("ROLE")) return "角色";
  if (r.includes("PLAN")) return "套餐";
  if (r.includes("COMPLIANCE") || r.includes("CONTENT")) return "内容";
  return "对象";
}
/** 操作人归一化：system/System/空 都收敛为「系统」。 */
function fmtOp(raw: string): string {
  if (!raw || raw === "—") return "—";
  if (/^system$/i.test(raw)) return "系统";
  return raw;
}

export default function Monitor() {
  const [services, setServices] = useState<ServiceItem[]>([]);
  const [llmProviders, setLlmProviders] = useState<LlmProviderItem[]>([]);
  const [auditLogs, setAuditLogs] = useState<AuditLogItem[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      fetchServices().then(setServices),
      fetchLlmProviders().then(setLlmProviders),
      fetchAuditLogs().then(setAuditLogs),
    ]).finally(() => setLoading(false));
  }, []);

  return (
    <div className="space-y-4">
      <div className="text-[15px]" style={{ color: C.mid }}>
        运行态数据来自网关埋点与各服务健康探针；LLM 共识集群异常时按优先级自动切换备用模型，全程留痕。
      </div>

      {/* 服务健康状态 */}
      <div className="grid grid-cols-5 gap-3">
        {services.map((s) => (
          <Card key={s.name} className="border shadow-none"
            style={{ borderColor: s.ok ? C.border : "#E5C07B", background: s.ok ? "#fff" : "#FFFBF2" }}>
            <CardContent className="p-4">
              <div className="flex items-center gap-1.5">
                {s.ok
                  ? <CheckCircle2 className="w-4 h-4" style={{ color: C.primary }} />
                  : <AlertTriangle className="w-4 h-4" style={{ color: "#8A6A1F" }} />}
                <span className="text-[15px] font-medium">{s.name}</span>
              </div>
              <div className="mt-2 text-[14px]" style={{ color: s.ok ? C.mid : "#8A6A1F" }}>{s.status}</div>
              <div className="mt-2 flex justify-between text-[13px]" style={{ color: C.light }}>
                <span>延迟 {s.latency}</span><span>可用率 {s.uptime}</span>
              </div>
            </CardContent>
          </Card>
        ))}
        {services.length === 0 && (
          <div className="col-span-5 py-10 text-center text-[15px]" style={{ color: C.light }}>
            {loading ? "加载中…" : "暂无服务数据"}
          </div>
        )}
      </div>

      {/* LLM用量 + 审计日志（上下结构，各占满宽，避免窄列拥挤） */}
      <div className="grid grid-cols-1 gap-4">
        {/* LLM 共识集群用量 */}
        <Card className="border shadow-none" style={{ borderColor: C.border }}>
          <CardContent className="p-4">
            <div className="flex items-center gap-2 mb-3">
              <Cpu className="w-4 h-4" style={{ color: C.primary }} />
              <span className="text-[16px] font-medium">LLM 共识集群可用性</span>
            </div>
            <table className="w-full text-[15px]">
              <thead>
                <tr className="text-left text-[13px]" style={{ color: C.light }}>
                  <th className="pb-2 font-normal">模型</th>
                  <th className="pb-2 font-normal">状态</th>
                  <th className="pb-2 font-normal text-right">连续失败</th>
                  <th className="pb-2 font-normal text-right">最近检查</th>
                </tr>
              </thead>
              <tbody>
                {llmProviders.map((m) => (
                  <tr key={m.name} className="border-t" style={{ borderColor: C.border }}>
                    <td className="py-2.5 font-medium">{m.name}</td>
                    <td className="py-2.5">
                      <span
                        className="text-[13px] px-2 py-0.5 rounded border"
                        style={m.available
                          ? { color: "#2E5A4C", background: "#EAF2EE", borderColor: "#CFE3DA" }
                          : { color: "#B03A2E", background: "#FDECEA", borderColor: "#F3C9C3" }}
                      >
                        {m.available ? "可用" : "不可用"}
                      </span>
                    </td>
                    <td className="py-2.5 text-right" style={{ color: m.failCount > 0 ? "#B03A2E" : C.mid }}>{m.failCount}</td>
                    <td className="py-2.5 text-right text-[13.5px]" style={{ color: C.light }}>
                      {m.lastCheck ? String(m.lastCheck).slice(0, 19).replace("T", " ") : "—"}
                    </td>
                  </tr>
                ))}
                {llmProviders.length === 0 && (
                  <tr>
                    <td colSpan={4} className="py-8 text-center text-[14px]" style={{ color: C.light }}>
                      {loading ? "加载中…" : "暂无模型状态数据"}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
            <div className="mt-3 p-2 rounded text-[13px] leading-relaxed" style={{ background: "#F8FAF9", color: C.mid }}>
              四模型共识 + 规则引擎仲裁：单模型异常自动降级不中断服务。后端当前仅上报可用性，分模型 token/成本计量口径尚未开放。
            </div>
          </CardContent>
        </Card>

        {/* 审计日志 */}
        <Card className="border shadow-none" style={{ borderColor: C.border }}>
          <CardContent className="p-4">
            <div className="flex items-center gap-2 mb-3">
              <ScrollText className="w-4 h-4" style={{ color: C.primary }} />
              <span className="text-[16px] font-medium">审计日志（控制端操作全留痕）</span>
            </div>
            <table className="w-full text-[15px]">
              <thead>
                <tr className="text-left text-[13px]" style={{ color: C.light }}>
                  {["时间", "操作人", "动作", "对象", "来源 IP"].map((h) => <th key={h} className="pb-2 font-normal">{h}</th>)}
                </tr>
              </thead>
              <tbody>
                {auditLogs.map((a, i) => {
                  const tone = toneOfAction(a.action);
                  const targetText = a.target && a.target !== "—" ? `${kindOfAction(a.action)} #${i + 1}` : "—";
                  return (
                  <tr key={i} className="border-t hover:bg-[#F8FAF9]" style={{ borderColor: C.border }}>
                    <td className="py-2.5 text-[14px]" style={{ color: C.mid }} title={a.time}>{fmtDateTime(a.time)}</td>
                    <td className="py-2.5">{fmtOp(a.op)}</td>
                    <td className="py-2.5">
                      <Badge variant="outline" className={`text-[13px] ${TONE_CLASS[tone]}`}>
                        {labelOfAction(a.action)}
                      </Badge>
                    </td>
                    <td className="py-2.5 text-[14px]" style={{ color: C.light }} title={a.target}>{targetText}</td>
                    <td className="py-2.5 font-mono text-[14px]" style={{ color: C.light }}>{a.ip || "—"}</td>
                  </tr>
                  );
                })}
                {auditLogs.length === 0 && (
                  <tr><td colSpan={5} className="py-10 text-center text-[15px]" style={{ color: C.light }}>{loading ? "加载中…" : "暂无审计日志"}</td></tr>
                )}
              </tbody>
            </table>
            <div className="mt-3 flex items-start gap-1 text-[13px] leading-relaxed" style={{ color: C.light }}>
              <span className="mt-0.5">💡</span>
              <span>日志保留 180 天，支持按操作人 / 动作 / 租户检索；高危操作（吊销密钥、租户降级）需二次确认并强制填写原因。</span>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
