import { useEffect, useState } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Cpu, ScrollText, CheckCircle2, AlertTriangle } from "lucide-react";
import { C } from "@/lib/types";
import { fetchServices, fetchLlmProviders, fetchAuditLogs } from "@/lib/api";
import type { ServiceItem, LlmProviderItem, AuditLogItem } from "@/lib/types";

/* 全量真实数据驱动：
   - 服务健康 → GET /admin/v1/monitor/services
   - 审计日志 → GET /admin/v1/audit-logs
   - LLM 分模型计量：后端暂无端点，返回空 → 显示诚实空态（不再回落 mock） */

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
      <div className="text-[13px]" style={{ color: C.mid }}>
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
                <span className="text-[13px] font-medium">{s.name}</span>
              </div>
              <div className="mt-2 text-[12px]" style={{ color: s.ok ? C.mid : "#8A6A1F" }}>{s.status}</div>
              <div className="mt-2 flex justify-between text-[11px]" style={{ color: C.light }}>
                <span>延迟 {s.latency}</span><span>可用率 {s.uptime}</span>
              </div>
            </CardContent>
          </Card>
        ))}
        {services.length === 0 && (
          <div className="col-span-5 py-10 text-center text-[13px]" style={{ color: C.light }}>
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
              <span className="text-[14px] font-medium">LLM 共识集群可用性</span>
            </div>
            <table className="w-full text-[13px]">
              <thead>
                <tr className="text-left text-[11px]" style={{ color: C.light }}>
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
                        className="text-[11px] px-2 py-0.5 rounded border"
                        style={m.available
                          ? { color: "#2E5A4C", background: "#EAF2EE", borderColor: "#CFE3DA" }
                          : { color: "#B03A2E", background: "#FDECEA", borderColor: "#F3C9C3" }}
                      >
                        {m.available ? "可用" : "不可用"}
                      </span>
                    </td>
                    <td className="py-2.5 text-right" style={{ color: m.failCount > 0 ? "#B03A2E" : C.mid }}>{m.failCount}</td>
                    <td className="py-2.5 text-right text-[11.5px]" style={{ color: C.light }}>
                      {m.lastCheck ? String(m.lastCheck).slice(0, 19).replace("T", " ") : "—"}
                    </td>
                  </tr>
                ))}
                {llmProviders.length === 0 && (
                  <tr>
                    <td colSpan={4} className="py-8 text-center text-[12px]" style={{ color: C.light }}>
                      {loading ? "加载中…" : "暂无模型状态数据"}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
            <div className="mt-3 p-2 rounded text-[11px] leading-relaxed" style={{ background: "#F8FAF9", color: C.mid }}>
              四模型共识 + 规则引擎仲裁：单模型异常自动降级不中断服务。后端当前仅上报可用性，分模型 token/成本计量口径尚未开放。
            </div>
          </CardContent>
        </Card>

        {/* 审计日志 */}
        <Card className="border shadow-none" style={{ borderColor: C.border }}>
          <CardContent className="p-4">
            <div className="flex items-center gap-2 mb-3">
              <ScrollText className="w-4 h-4" style={{ color: C.primary }} />
              <span className="text-[14px] font-medium">审计日志（控制端操作全留痕）</span>
            </div>
            <table className="w-full text-[13px]">
              <thead>
                <tr className="text-left text-[11px]" style={{ color: C.light }}>
                  {["时间", "操作人", "动作", "对象", "来源 IP"].map((h) => <th key={h} className="pb-2 font-normal">{h}</th>)}
                </tr>
              </thead>
              <tbody>
                {auditLogs.map((a, i) => (
                  <tr key={i} className="border-t hover:bg-[#F8FAF9]" style={{ borderColor: C.border }}>
                    <td className="py-2.5 font-mono text-[12px]" style={{ color: C.mid }}>{a.time}</td>
                    <td className="py-2.5">{a.op}</td>
                    <td className="py-2.5">
                      <Badge variant="outline" className={`font-mono text-[11px] ${
                        a.action.includes("approve") ? "bg-emerald-50 text-emerald-700 border-emerald-200" :
                        a.action.includes("create") ? "bg-sky-50 text-sky-700 border-sky-200" :
                        a.action.includes("rotate") || a.action.includes("readonly") ? "bg-amber-50 text-amber-700 border-amber-200" :
                        "bg-gray-50 text-gray-600 border-gray-200"
                      }`}>
                        {a.action}
                      </Badge>
                    </td>
                    <td className="py-2.5 text-[12px]">{a.target}</td>
                    <td className="py-2.5 font-mono text-[12px]" style={{ color: C.light }}>{a.ip}</td>
                  </tr>
                ))}
                {auditLogs.length === 0 && (
                  <tr><td colSpan={5} className="py-10 text-center text-[13px]" style={{ color: C.light }}>{loading ? "加载中…" : "暂无审计日志"}</td></tr>
                )}
              </tbody>
            </table>
            <div className="mt-3 flex items-start gap-1 text-[11px] leading-relaxed" style={{ color: C.light }}>
              <span className="mt-0.5">💡</span>
              <span>日志保留 180 天，支持按操作人 / 动作 / 租户检索；高危操作（吊销密钥、租户降级）需二次确认并强制填写原因。</span>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
