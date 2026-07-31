import { useEffect, useState } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Cpu, ScrollText, CheckCircle2, AlertTriangle } from "lucide-react";
import { C } from "@/lib/types";
import { fetchServices, fetchLlmUsage, fetchAuditLogs } from "@/lib/api";
import type { ServiceItem, LlmUsageItem, AuditLogItem } from "@/lib/types";

const MOCK_SERVICES: ServiceItem[] = [
  { name: "API 网关", status: "运行正常", latency: "42ms", uptime: "99.98%", ok: true },
  { name: "中台应用 (FastAPI)", status: "运行正常", latency: "186ms", uptime: "99.95%", ok: true },
  { name: "Neo4j 图谱库", status: "运行正常", latency: "12ms", uptime: "99.99%", ok: true },
  { name: "PostgreSQL 业务库", status: "运行正常", latency: "8ms", uptime: "99.99%", ok: true },
  { name: "LLM 共识集群", status: "DeepSeek 备用切换中", latency: "1240ms", uptime: "99.91%", ok: false },
];

const MOCK_LLM: LlmUsageItem[] = [
  { model: "DeepSeek", tokens: 3120, cost: 84.2 },
  { model: "GLM-4", tokens: 980, cost: 39.6 },
  { model: "Kimi", tokens: 720, cost: 33.5 },
  { model: "通义千问", tokens: 600, cost: 25.1 },
];

const MOCK_AUDIT: AuditLogItem[] = [
  { time: "2026-07-26 14:32", op: "王运营", action: "api_key.rotate", target: "K-04（杏林在线）", ip: "10.8.0.12" },
  { time: "2026-07-26 11:05", op: "李商务", action: "tenant.create", target: "天津颐和堂大药房连锁", ip: "10.8.0.15" },
  { time: "2026-07-26 09:47", op: "张内容", action: "content.review.approve", target: "KR-8805 麸炒白术", ip: "10.8.0.21" },
  { time: "2026-07-25 18:20", op: "王运营", action: "tenant.status.readonly", target: "杏林在线教育学院", ip: "10.8.0.12" },
  { time: "2026-07-25 16:08", op: "系统", action: "billing.bill.generate", target: "2026-07 账期 × 5", ip: "—" },
];

export default function Monitor() {
  const [services, setServices] = useState<ServiceItem[]>([]);
  const [llmUsage, setLlmUsage] = useState<LlmUsageItem[]>([]);
  const [auditLogs, setAuditLogs] = useState<AuditLogItem[]>([]);

  useEffect(() => {
    fetchServices().then(data => setServices(data.length ? data : MOCK_SERVICES));
    fetchLlmUsage().then(data => setLlmUsage(data.length ? data : MOCK_LLM));
    fetchAuditLogs().then(data => setAuditLogs(data.length ? data : MOCK_AUDIT));
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
          <div className="col-span-5 py-10 text-center text-[13px]" style={{ color: C.light }}>暂无服务数据</div>
        )}
      </div>

      {/* LLM用量 + 审计日志 */}
      <div className="grid grid-cols-5 gap-4">
        {/* LLM 共识集群用量 */}
        <Card className="col-span-2 border shadow-none" style={{ borderColor: C.border }}>
          <CardContent className="p-4">
            <div className="flex items-center gap-2 mb-3">
              <Cpu className="w-4 h-4" style={{ color: C.primary }} />
              <span className="text-[14px] font-medium">LLM 共识集群用量（本月）</span>
            </div>
            <table className="w-full text-[13px]">
              <thead>
                <tr className="text-left text-[11px]" style={{ color: C.light }}>
                  <th className="pb-2 font-normal">模型</th>
                  <th className="pb-2 font-normal text-right">Token（万）</th>
                  <th className="pb-2 font-normal text-right">成本（¥）</th>
                  <th className="pb-2 font-normal text-right">占比</th>
                </tr>
              </thead>
              <tbody>
                {llmUsage.map((m) => {
                  const total = llmUsage.reduce((a, b) => a + b.tokens, 1);
                  return (
                    <tr key={m.model} className="border-t" style={{ borderColor: C.border }}>
                      <td className="py-2.5">{m.model}</td>
                      <td className="py-2.5 text-right">{m.tokens.toLocaleString()}</td>
                      <td className="py-2.5 text-right">{m.cost.toFixed(1)}</td>
                      <td className="py-2.5 text-right">
                        <div className="flex items-center justify-end gap-2">
                          <div className="w-16 h-1.5 rounded-full" style={{ background: C.soft }}>
                            <div className="h-1.5 rounded-full" style={{ width: `${(m.tokens / total) * 100}%`, background: C.primary }} />
                          </div>
                          <span className="text-[11px]" style={{ color: C.light }}>{Math.round((m.tokens / total) * 100)}%</span>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            <div className="mt-3 p-2 rounded text-[11px] leading-relaxed" style={{ background: "#F8FAF9", color: C.mid }}>
              四模型共识 + 规则引擎仲裁：单模型异常不中断服务；成本按租户维度归集，计入计量计费账期。
            </div>
          </CardContent>
        </Card>

        {/* 审计日志 */}
        <Card className="col-span-3 border shadow-none" style={{ borderColor: C.border }}>
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
                  <tr><td colSpan={5} className="py-10 text-center text-[13px]" style={{ color: C.light }}>暂无审计日志</td></tr>
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
