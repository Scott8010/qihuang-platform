/** 通用人类可读格式化 helper */

/** ISO 时间戳友好显示：
 *  - "2026-08-21T16:31:55.226336" -> "2026-08-21 16:31"
 *  - "2027-08-01T00:00:00"       -> "2027-08-01"  (HH:MM 是 00:00 时按纯日期收敛)
 *  - "2026-08-21"                -> "2026-08-21"
 *  - 空值 -> "—"；异常 passthrough 兜底
 */
export function fmtDateTime(s?: string | null): string {
  if (!s) return "—";
  const m = String(s).match(/^(\d{4}-\d{2}-\d{2})(?:T(\d{2}):(\d{2}):\d{2}(?:\.\d+)?)?/);
  if (!m) return String(s);
  const date = m[1];
  if (m[2] && m[3] && !(m[2] === "00" && m[3] === "00")) {
    return `${date} ${m[2]}:${m[3]}`;
  }
  return date;
}
