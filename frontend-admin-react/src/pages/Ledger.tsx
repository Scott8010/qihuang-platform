import { C } from "@/lib/types";

/**
 * 双账本页面：内嵌独立账本报告页（/admin/billing_ledger.html，已归口到 React 静态资源 public/）。
 * 该报告页复用 localStorage["qh_admin_token"]（与控制台登录态同源共享），
 * 因此无需重写鉴权——iframe 内自动带 token 拉取 /admin/v1/billing/usage。
 *
 * 口径（老板拍板 2026-09-12）：
 *  - 左栏「租户/客户消耗账本」= 8602 call_log，可计费
 *  - 右栏「平台自身成本·自生长引擎」= 8601 token 消耗，平台承担，不计入租户账单
 */
export default function Ledger() {
  return (
    <div
      style={{
        width: "100%",
        height: "calc(100vh - 112px)",
        background: "#fff",
        borderRadius: 12,
        overflow: "hidden",
        border: `1px solid ${C.border}`,
      }}
    >
      <iframe
        src="/admin/billing_ledger.html"
        title="双账本 · 平台成本与租户消耗"
        style={{ width: "100%", height: "100%", border: "none" }}
      />
    </div>
  );
}
