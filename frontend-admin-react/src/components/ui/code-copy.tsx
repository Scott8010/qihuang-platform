import { useState } from "react";
import { Copy, Check } from "lucide-react";

/** 编码单元格：完整展示后端真实 ID（如 UUID），不截断、不折行；
 *  悬停出现「复制」按钮，点击写入剪贴板并短暂显示已复制。
 *  避免把程序内部编码直接裸露成难以辨认的长串——可读 + 可复制。 */
export function CodeCopy({ value, className = "", short = false }: { value: string; className?: string; short?: boolean }) {
  const [copied, setCopied] = useState(false);

  const display = short && value.length > 14 ? `${value.slice(0, 8)}…${value.slice(-4)}` : value;

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value);
    } catch {
      const ta = document.createElement("textarea");
      ta.value = value;
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      try { document.execCommand("copy"); } catch { /* noop */ }
      document.body.removeChild(ta);
    }
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  return (
    <span
      className={`group/code inline-flex items-center gap-1.5 font-mono whitespace-nowrap align-middle ${className}`}
      title={value}
    >
      <span className="text-foreground/80">{display}</span>
      <button
        type="button"
        onClick={copy}
        title="复制完整编码"
        className="inline-flex items-center justify-center w-5 h-5 rounded border border-border text-muted-foreground opacity-0 group-hover/code:opacity-100 transition-opacity hover:text-foreground hover:bg-secondary"
      >
        {copied ? <Check className="w-3 h-3 text-emerald-600" /> : <Copy className="w-3 h-3" />}
      </button>
    </span>
  );
}
