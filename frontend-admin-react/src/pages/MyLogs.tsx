import { useState, useEffect } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Loader2, Download, Search } from "lucide-react";
import { C } from "@/lib/types";
import { fetchMyCallLogs, type CallLogItem } from "@/lib/api";
import { bjTime } from "./MyTickets";

type Kind = "business" | "operation";

/**
 * 客户工作台「使用日志」：按租户查看调用明细，并可导出表格。
 * 口径（2026-11-19 A）：
 *   - AI 调用（business）：真业务调用，计入用量与账单。
 *   - 后台操作（operation）：登录/查看页面/读钱包等，不计入用量与账单。
 * 两路都走 my/call-logs，后端按 token 租户强制收窄，跨租户拿不到。
 */
export default function MyLogs() {
  const [kind, setKind] = useState<Kind>("business");
  const [days, setDays] = useState(7);
  const [endpoint, setEndpoint] = useState("");
  const [statusCode, setStatusCode] = useState("");
  const [page, setPage] = useState(1);
  const [items, setItems] = useState<CallLogItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const pageSize = 20;

  useEffect(() => {
    let alive = true;
    setLoading(true);
    fetchMyCallLogs({
      days, endpoint: endpoint.trim() || undefined,
      status_code: statusCode ? Number(statusCode) : undefined,
      page, page_size: pageSize, kind,
    }).then((r) => {
      if (!alive) return;
      setItems(r.items); setTotal(r.total); setLoading(false);
    });
    return () => { alive = false; };
  }, [kind, days, endpoint, statusCode, page]);

  const exportCsv = () => {
    const head = ["时间(北京时间)", "接口", "方法", "状态码", "耗时(ms)", "Tokens", "费用(元)", "密钥"];
    const rows = items.map((x) => [
      bjTime(x.timestamp), x.endpoint, x.method, String(x.status_code),
      String(x.latency_ms), String(x.tokens_used), String((x.cost_cents || 0) / 100), x.app_key,
    ]);
    const csv = "\ufeff" + [head, ...rows].map((r) => r.map((v) => `"${String(v).replace(/"/g, '""')}"`).join(",")).join("\r\n");
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
    const a = document.createElement("a");
    a.href = url; a.download = `${kind === "business" ? "AI调用日志" : "后台操作日志"}_${new Date().toISOString().slice(0, 10)}.csv`;
    a.click(); URL.revokeObjectURL(url);
  };

  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const switchKind = (k: Kind) => { setKind(k); setPage(1); };

  return (
    <div className="space-y-5">
      <div className="rounded-lg p-3 text-[13px] leading-relaxed" style={{ background: C.soft, border: `1px solid ${C.border}`, color: C.mid }}>
        <b style={{ color: C.primary }}>AI 调用</b>是真正用到能力、会计入用量与账单的记录；
        <b style={{ color: C.primary }}>后台操作</b>是登录、查看页面、读钱包等请求，<b>不计入用量与账单</b>。
        想查某个报错，可按接口路径或状态码筛选，再把当前页导出成表格发给平台方。
      </div>

      <Card className="border" style={{ borderColor: C.border }}>
        <CardHeader className="pb-2">
          <div className="flex items-center justify-between gap-3 flex-wrap">
            <CardTitle className="text-[16px]" style={{ color: C.primary }}>
              {kind === "business" ? "AI 调用明细" : "后台操作日志"}
            </CardTitle>
            <Button variant="outline" size="sm" onClick={exportCsv} disabled={items.length === 0} className="text-[13px]">
              <Download className="w-3.5 h-3.5 mr-1" />导出当前页
            </Button>
          </div>
          {/* 口径切换 */}
          <div className="flex rounded-lg p-0.5 mt-3 w-fit" style={{ background: C.bg }}>
            <button onClick={() => switchKind("business")}
              className="px-4 py-1.5 text-[13px] rounded-md"
              style={kind === "business" ? { background: "#fff", color: C.primary, fontWeight: 600 } : { color: C.mid }}>
              AI 调用 <span className="text-[11px]">(计入用量)</span>
            </button>
            <button onClick={() => switchKind("operation")}
              className="px-4 py-1.5 text-[13px] rounded-md"
              style={kind === "operation" ? { background: "#fff", color: C.primary, fontWeight: 600 } : { color: C.mid }}>
              后台操作 <span className="text-[11px]">(不计入)</span>
            </button>
          </div>
        </CardHeader>
        <CardContent>
          <div className="flex gap-3 mb-4 flex-wrap items-center">
            <select value={days} onChange={(e) => { setDays(Number(e.target.value)); setPage(1); }}
              className="px-3 py-2 rounded-lg border text-[13px] bg-white" style={{ borderColor: C.border, color: C.ink }}>
              {[7, 30, 90].map((d) => <option key={d} value={d}>近 {d} 天</option>)}
            </select>
            <div className="relative">
              <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2" style={{ color: C.light }} />
              <input value={endpoint} onChange={(e) => { setEndpoint(e.target.value); setPage(1); }}
                placeholder="搜接口路径，如 consult"
                className="pl-9 pr-3 py-2 rounded-lg border text-[13px] outline-none w-60"
                style={{ borderColor: C.border }} />
            </div>
            <select value={statusCode} onChange={(e) => { setStatusCode(e.target.value); setPage(1); }}
              className="px-3 py-2 rounded-lg border text-[13px] bg-white" style={{ borderColor: C.border, color: C.ink }}>
              <option value="">全部状态</option>
              {[200, 400, 401, 403, 429, 500].map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
            <span className="text-[13px]" style={{ color: C.light }}>共 {total.toLocaleString("zh-CN")} 条</span>
          </div>

          {loading ? (
            <div className="flex items-center gap-2 py-12 justify-center text-[14px]" style={{ color: C.light }}>
              <Loader2 className="w-4 h-4 animate-spin" />加载中…
            </div>
          ) : items.length === 0 ? (
            <div className="py-12 text-center text-[14px]" style={{ color: C.light }}>
              {kind === "business" ? "这个时间段没有 AI 调用记录。" : "这个时间段没有后台操作记录。"}
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-[13px]">
                <thead>
                  <tr className="text-left" style={{ color: C.light }}>
                    {["时间", "接口", "方法", "状态", "耗时", "Tokens", "费用", "密钥"].map((h) => (
                      <th key={h} className="py-2 pr-3 font-normal whitespace-nowrap">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {items.map((x) => (
                    <tr key={x.id} className="border-t" style={{ borderColor: C.border }}>
                      <td className="py-2.5 pr-3 whitespace-nowrap" style={{ color: C.mid }}>{bjTime(x.timestamp)}</td>
                      <td className="py-2.5 pr-3 max-w-[260px] truncate" style={{ color: C.ink }} title={x.endpoint}>{x.endpoint}</td>
                      <td className="py-2.5 pr-3" style={{ color: C.mid }}>{x.method}</td>
                      <td className="py-2.5 pr-3">
                        <span style={{ color: x.status_code < 400 ? "#2E5A4C" : "#B03A2E" }}>{x.status_code}</span>
                      </td>
                      <td className="py-2.5 pr-3" style={{ color: C.mid }}>{x.latency_ms} ms</td>
                      <td className="py-2.5 pr-3" style={{ color: C.mid }}>{(x.tokens_used || 0).toLocaleString("zh-CN")}</td>
                      <td className="py-2.5 pr-3" style={{ color: C.mid }}>¥{((x.cost_cents || 0) / 100).toFixed(2)}</td>
                      <td className="py-2.5 pr-3" style={{ color: C.light }}>{x.app_key || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <div className="flex items-center justify-end gap-3 pt-4 text-[13px]" style={{ color: C.mid }}>
                <span>第 {page} / {totalPages} 页</span>
                <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>上一页</Button>
                <Button variant="outline" size="sm" disabled={page >= totalPages} onClick={() => setPage((p) => p + 1)}>下一页</Button>
              </div>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
