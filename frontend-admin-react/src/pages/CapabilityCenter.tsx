import { useEffect, useState } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter,
} from "@/components/ui/dialog";
import {
  Boxes, Globe, Lock, FilePlus2, Send, CheckCircle2, XCircle, Loader2,
  ShieldCheck, Eye, Info, FlaskConical,
  ListOrdered, MapPin, ClipboardList, BookOpen, Sparkles,
  History, Undo2, BarChart3, Pencil,
} from "lucide-react";
import { C } from "@/lib/types";
import {
  fetchCapabilityTemplates, fetchCapabilitySubmissions, createCapabilityTemplate,
  updateCapabilityTemplate, submitCapabilityTemplate, approveCapabilitySubmission, rejectCapabilitySubmission,
  fetchCapabilityTemplateVersions, rollbackCapabilityTemplate, fetchCapabilityStats,
  type CapabilityTemplate, type CapabilitySubmission, type CapabilityVersion, type CapabilityStats,
} from "@/lib/api";
import TemplateEditor, { TextImporter, defaultContentFor } from "@/components/capability/TemplateEditor";
import { toast } from "sonner";

/* ═══════════════════════════════════════════
   多租户能力中心 — 模板市场 + 平台审核工作台
   后端 /admin/v1/template-center/*（已上线）

   业务定位（二期·多租户能力中心）：
     解决门店问卷 / 课件知识切片 / 项目 SOP / 产品培训 / 话术脚本
     等"可复用能力资产"在「平台 ↔ 机构」之间的归属与流转：
       · 平台官方模板  → 全网租户可见（共享池基线）
       · 机构自建模板  → 默认私有，仅本机构可见
       · 同步提交平台  → 进入「审核工作台」
       · 平台采纳      → 提升为共享池（public），其他机构可克隆复用
       · 平台驳回/强下架→ 收回私有，不允许再出现于共享池
   ═══════════════════════════════════════════ */

const KIND_LABEL: Record<string, string> = {
  herb: "中药", formula: "方剂", syndrome: "证候", disease: "疾病",
  script: "话术脚本", product: "产品培训", project: "项目培训", knowledge: "知识课件", other: "其他",
};


/* ─────────────── 详情弹窗用：4 套已知 schema 渲染器 ─────────────── */

/** ① 知识课件 § 章节型（艾灸养生）：{category, content:[{title,body}], talk_script?} */
function KnowledgeSectionsView({ data }: { data: Record<string, unknown> }) {
  const items = Array.isArray(data.content) ? (data.content as Array<{ title?: string; body?: string }>) : [];
  return (
    <div className="space-y-3">
      <FieldRow label="主题分类" value={safeStr(data.category)} icon={<BookOpen className="w-3.5 h-3.5" />} />
      <div className="space-y-1.5">
        <div className="text-[13px] flex items-center gap-1" style={{ color: C.light }}>
          <ListOrdered className="w-3 h-3" />知识章节 <span className="text-[12px]">（共 {items.length} 节）</span>
        </div>
        <ol className="space-y-1.5">
          {items.map((s, i) => (
            <li key={i} className="flex gap-2 rounded-md border px-2.5 py-2" style={{ borderColor: C.border, background: "#FCFCFA" }}>
              <span className="shrink-0 w-5 h-5 rounded-full text-[12.5px] font-bold flex items-center justify-center"
                style={{ background: C.primary, color: "#fff" }}>{i + 1}</span>
              <div className="min-w-0 flex-1">
                <div className="text-[14.5px] font-medium" style={{ color: C.ink }}>{s.title || `第 ${i + 1} 节`}</div>
                <div className="text-[13.5px] mt-0.5 leading-relaxed whitespace-pre-wrap" style={{ color: C.mid }}>{s.body || "—"}</div>
              </div>
            </li>
          ))}
        </ol>
      </div>
      {typeof data.talk_script === "string" && data.talk_script && (
        <TalkScript value={data.talk_script} />
      )}
    </div>
  );
}

/** ② 知识课件 § 穴位型（经络穴位）：{category, points:[{name,meridian,location,effect,moxa_method,cautions[],talk_script}], common_cautions[]} */
function KnowledgePointsView({ data }: { data: Record<string, unknown> }) {
  const points = Array.isArray(data.points) ? data.points as Array<Record<string, unknown>> : [];
  const cautions = Array.isArray(data.common_cautions) ? data.common_cautions as string[] : [];
  return (
    <div className="space-y-3">
      <FieldRow label="主题分类" value={safeStr(data.category)} icon={<BookOpen className="w-3.5 h-3.5" />} />
      <div className="space-y-1.5">
        <div className="text-[13px] flex items-center gap-1" style={{ color: C.light }}>
          <MapPin className="w-3 h-3" />穴位 <span className="text-[12px]">（共 {points.length} 个）</span>
        </div>
        <div className="grid grid-cols-1 gap-1.5">
          {points.map((p, i) => {
            const cs = Array.isArray(p.cautions) ? p.cautions as string[] : [];
            return (
              <div key={i} className="rounded-md border px-2.5 py-2 space-y-1" style={{ borderColor: C.border, background: "#FCFCFA" }}>
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-[14.5px] font-semibold" style={{ color: C.ink }}>{safeStr(p.name)}</span>
                  {p.meridian ? (
                    <span className="text-[12px] px-1.5 py-0.5 rounded" style={{ background: "#FBF4E4", color: "#8A6A1F" }}>
                      {safeStr(p.meridian)}
                    </span>
                  ) : null}
                </div>
                {p.location ? <FieldRowInline label="定位" value={safeStr(p.location)} /> : null}
                {p.effect ? <FieldRowInline label="功效" value={safeStr(p.effect)} /> : null}
                {p.moxa_method ? <FieldRowInline label="灸法" value={safeStr(p.moxa_method)} /> : null}
                {cs.length > 0 && (
                  <FieldRowInline label="禁忌" value={cs.join(" · ")} tone="warn" />
                )}
                {typeof p.talk_script === "string" && p.talk_script && <TalkScript value={p.talk_script} />}
              </div>
            );
          })}
        </div>
      </div>
      {cautions.length > 0 && (
        <div className="rounded-md border px-2.5 py-2" style={{ borderColor: "#F0D9B5", background: "#FFF8EC" }}>
          <div className="text-[13px] font-medium mb-1" style={{ color: "#8A6A1F" }}>⚠ 通用注意事项</div>
          <ul className="text-[13.5px] space-y-0.5" style={{ color: "#6B5212" }}>
            {cautions.map((c, i) => <li key={i}>· {c}</li>)}
          </ul>
        </div>
      )}
    </div>
  );
}

/** ③ 项目 SOP：{type, duration_min, flow:[{step,name,script}], cautions[], aftercare[]} */
function ProjectFlowView({ data }: { data: Record<string, unknown> }) {
  const flow = Array.isArray(data.flow) ? data.flow as Array<Record<string, unknown>> : [];
  const cautions = Array.isArray(data.cautions) ? data.cautions as string[] : [];
  const aftercare = Array.isArray(data.aftercare) ? data.aftercare as string[] : [];
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2">
        {data.type ? <FieldRow label="项目类型" value={safeStr(data.type)} /> : null}
        {typeof data.duration_min === "number" ? (
          <FieldRow label="时长" value={`${data.duration_min} 分钟`} />
        ) : null}
      </div>
      <div className="space-y-1.5">
        <div className="text-[13px] flex items-center gap-1" style={{ color: C.light }}>
          <ClipboardList className="w-3 h-3" />服务流程 <span className="text-[12px]">（共 {flow.length} 步）</span>
        </div>
        <ol className="space-y-1">
          {flow.map((s, i) => (
            <li key={i} className="flex gap-2 rounded-md border px-2.5 py-1.5" style={{ borderColor: C.border, background: "#FCFCFA" }}>
              <span className="shrink-0 w-5 h-5 rounded-full text-[12.5px] font-bold flex items-center justify-center"
                style={{ background: C.accent, color: "#fff" }}>
                {typeof s.step === "number" ? s.step : i + 1}
              </span>
              <div className="min-w-0 flex-1">
                <div className="text-[14px] font-medium" style={{ color: C.ink }}>{safeStr(s.name)}</div>
                {s.script ? <div className="text-[13px] mt-0.5 leading-relaxed" style={{ color: C.mid }}>{safeStr(s.script)}</div> : null}
              </div>
            </li>
          ))}
        </ol>
      </div>
      {cautions.length > 0 && (
        <CautionsBlock title="禁忌 / 注意事项" items={cautions} />
      )}
      {aftercare.length > 0 && (
        <CautionsBlock title="善后建议" items={aftercare} tone="info" />
      )}
    </div>
  );
}

/** ④ 产品培训：{type, ingredients[], positioning, usage, suitable, cautions[], sales_points[]} */
function ProductTrainingView({ data }: { data: Record<string, unknown> }) {
  const ingredients = Array.isArray(data.ingredients) ? data.ingredients as string[] : [];
  const cautions = Array.isArray(data.cautions) ? data.cautions as string[] : [];
  const sales = Array.isArray(data.sales_points) ? data.sales_points as string[] : [];
  return (
    <div className="space-y-2.5">
      <div className="flex flex-wrap gap-2">
        {data.type ? <FieldRow label="品类" value={safeStr(data.type)} /> : null}
        {data.positioning ? <FieldRow label="定位" value={safeStr(data.positioning)} /> : null}
      </div>
      {data.usage ? <FieldRow label="用法" value={safeStr(data.usage)} /> : null}
      {data.suitable ? <FieldRow label="适宜人群" value={safeStr(data.suitable)} /> : null}
      {ingredients.length > 0 && (
        <div>
          <div className="text-[13px] mb-1" style={{ color: C.light }}>配方 / 成分</div>
          <div className="flex flex-wrap gap-1">
            {ingredients.map((s, i) => (
              <span key={i} className="text-[13px] px-2 py-0.5 rounded-full" style={{ background: C.soft, color: C.primary }}>{s}</span>
            ))}
          </div>
        </div>
      )}
      {sales.length > 0 && (
        <div>
          <div className="text-[13px] mb-1" style={{ color: C.light }}>销售卖点</div>
          <div className="flex flex-wrap gap-1">
            {sales.map((s, i) => (
              <span key={i} className="text-[13px] px-2 py-0.5 rounded-full border" style={{ borderColor: "#F5EDD9", color: "#8A6A1F", background: "#FBF4E4" }}>{s}</span>
            ))}
          </div>
        </div>
      )}
      {cautions.length > 0 && <CautionsBlock title="注意事项" items={cautions} />}
    </div>
  );
}

/** ⑤ 问卷草稿：{from_questionnaire, schema} 或 schema 详情 */
function QuestionnaireDraftView({ data }: { data: Record<string, unknown> }) {
  const schema = data.schema as Record<string, unknown> | undefined;
  const title = (typeof schema?.title === "string" ? schema.title : "")
    || (typeof data.title === "string" ? data.title : "")
    || "问卷草稿";
  const fields = Array.isArray(schema?.fields)
    ? schema!.fields as Array<Record<string, unknown>>
    : Array.isArray(schema?.questions)
      ? schema!.questions as Array<Record<string, unknown>>
      : [];
  return (
    <div className="space-y-2.5">
      <FieldRow label="来源" value={`问卷 · ${safeStr(data.from_questionnaire) || "—"}`} icon={<FlaskConical className="w-3.5 h-3.5" />} />
      <FieldRow label="名称" value={title} />
      {schema?.description ? <FieldRow label="说明" value={safeStr(schema.description)} /> : null}
      {fields.length > 0 && (
        <div>
          <div className="text-[13px] mb-1" style={{ color: C.light }}>字段（{fields.length}）</div>
          <div className="rounded-md border divide-y" style={{ borderColor: C.border }}>
            {fields.map((f, i) => (
              <div key={i} className="px-2.5 py-1.5 flex items-baseline gap-2 text-[13.5px]" style={{ borderColor: C.border }}>
                <span className="font-medium" style={{ color: C.ink }}>{String(f.label || f.name || f.key || `字段 ${i + 1}`)}</span>
                <span className="text-[12px] px-1 py-0.5 rounded font-mono" style={{ background: C.soft, color: C.primary }}>
                  {String(f.type || f.field_type || "—")}
                </span>
                {!!f.required && <span className="text-[12px] text-red-600">*必填</span>}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

/** 话术脚本（紫色特别行，店员可直接读） */
function TalkScript({ value }: { value: string }) {
  return (
    <div className="rounded-md px-2 py-1.5 text-[13.5px] leading-relaxed italic"
      style={{ background: "#F2EFEA", color: "#5B4F35", borderLeft: `3px solid ${C.accent}` }}>
      💬 {value}
    </div>
  );
}

/** 顶部 key-value 横排 */
function FieldRow({ label, value, icon }: { label: string; value: string; icon?: React.ReactNode }) {
  return (
    <div className="inline-flex items-center gap-1.5 text-[13.5px] px-2 py-1 rounded border" style={{ borderColor: C.border, background: "#F8FAF9" }}>
      <span className="flex items-center gap-1" style={{ color: C.light }}>{icon}{label}</span>
      <span style={{ color: C.ink }}>{value || "—"}</span>
    </div>
  );
}
function FieldRowInline({ label, value, tone }: { label: string; value: string; tone?: "warn" | "info" }) {
  const color = tone === "warn" ? "#8A6A1F" : tone === "info" ? "#3D5A80" : C.mid;
  return (
    <div className="text-[13.5px] leading-relaxed">
      <span style={{ color: C.light }}>{label}：</span>
      <span style={{ color }}>{value}</span>
    </div>
  );
}

/** 把 unknown 安全转 string（避免 TS unknown→ReactNode 冲突） */
function safeStr(v: unknown): string {
  if (v === null || v === undefined) return "";
  if (typeof v === "string") return v;
  if (typeof v === "number" || typeof v === "boolean") return String(v);
  return String(v);
}

/** 注意事项红/蓝块 */
function CautionsBlock({ title, items, tone }: { title: string; items: string[]; tone?: "warn" | "info" }) {
  const warn = tone !== "info";
  return (
    <div className="rounded-md border px-2.5 py-2"
      style={{ borderColor: warn ? "#F0D9B5" : "#C9D9EA", background: warn ? "#FFF8EC" : "#F3F7FB" }}>
      <div className="text-[13px] font-medium mb-1" style={{ color: warn ? "#8A6A1F" : "#3D5A80" }}>
        {warn ? "⚠" : "ℹ"} {title}
      </div>
      <ul className="text-[13.5px] space-y-0.5" style={{ color: warn ? "#6B5212" : "#2F4A6A" }}>
        {items.map((c, i) => <li key={i}>· {c}</li>)}
      </ul>
    </div>
  );
}

/** ⑥ 未知 schema fallback：KV 平铺 + 折叠 JSON + 复制 */
function GenericKVView({ value, depth = 0 }: { value: unknown; depth?: number }) {
  if (value === null || value === undefined) {
    return <span className="text-[13.5px]" style={{ color: C.light }}>—</span>;
  }
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return (
      <span className="text-[13.5px] break-all" style={{ color: C.ink }}>
        {typeof value === "string" ? `「${value}」` : String(value)}
      </span>
    );
  }
  if (Array.isArray(value)) {
    if (value.length === 0) return <span className="text-[13.5px]" style={{ color: C.light }}>（空）</span>;
    return (
      <ol className="space-y-1 list-decimal pl-4">
        {value.map((v, i) => (
          <li key={i} className="text-[13.5px]">
            <GenericKVView value={v} depth={depth + 1} />
          </li>
        ))}
      </ol>
    );
  }
  if (typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>);
    if (entries.length === 0) return <span className="text-[13.5px]" style={{ color: C.light }}>（空对象）</span>;
    return (
      <div className={depth === 0 ? "space-y-1 rounded-md border p-2" : "space-y-1"} style={{ borderColor: C.border, background: depth === 0 ? "#FCFCFA" : undefined }}>
        {entries.map(([k, v]) => (
          <div key={k} className="grid grid-cols-[auto_1fr] gap-x-2 items-baseline text-[13.5px]">
            <span className="font-medium" style={{ color: C.mid }}>{k}</span>
            <GenericKVView value={v} depth={depth + 1} />
          </div>
        ))}
      </div>
    );
  }
  return null;
}

/** 运营统计小方块 */
function StatTile({ label, value, tone }: { label: string; value: number; tone?: "warn" }) {
  return (
    <div className="rounded-md border px-2.5 py-2 text-center" style={{ borderColor: C.border, background: "#fff" }}>
      <div className="text-[20px] font-bold leading-none" style={{ color: tone === "warn" ? "#8A6A1F" : C.primary }}>{value}</div>
      <div className="text-[13px] mt-1" style={{ color: C.light }}>{label}</div>
    </div>
  );
}

/* ─────────────── 内容渲染路由入口 ─────────────── */
function TemplatePreview({ content }: { content: Record<string, unknown> }) {
  // ① 知识课件章节型（艾灸养生）：category + content:[{title,body}]
  if (Array.isArray(content.content) && (content.content as unknown[]).every(
    (x) => x && typeof x === "object" && ("title" in (x as object) || "body" in (x as object))
  )) {
    return <KnowledgeSectionsView data={content} />;
  }
  // ② 知识课件穴位型（经络穴位）：points:[{name,meridian,...}]
  if (Array.isArray(content.points) && (content.points as unknown[]).every(
    (x) => x && typeof x === "object" && "name" in (x as object)
  )) {
    return <KnowledgePointsView data={content} />;
  }
  // ③ 项目 SOP：flow:[{step,name,script}]
  if (Array.isArray(content.flow) && (content.flow as unknown[]).every(
    (x) => x && typeof x === "object" && ("script" in (x as object) || "name" in (x as object))
  )) {
    return <ProjectFlowView data={content} />;
  }
  // ④ 产品培训：ingredients + positioning + (usage|suitable)
  if (Array.isArray(content.ingredients) && (content.positioning || content.usage || content.suitable)) {
    return <ProductTrainingView data={content} />;
  }
  // ⑤ 问卷草稿：{from_questionnaire, schema}
  if (content.from_questionnaire || (content.schema && typeof content.schema === "object")) {
    return <QuestionnaireDraftView data={content} />;
  }
  // ⑥ 自由 schema：先平铺，再附折叠 JSON
  return <GenericSchemaView content={content} />;
}

/** 未知 schema：KV 平铺 + 折叠 JSON（语法高亮 + 复制） */
function GenericSchemaView({ content }: { content: Record<string, unknown> }) {
  return (
    <div>
      <GenericKVView value={content} />
    </div>
  );
}

/** 详情元信息：归属 + 版本 + ID + Created（统一排版） */
function TemplateMeta({ tpl }: { tpl: CapabilityTemplate }) {
  const vis = visInfo(tpl.ownership?.visibility);
  const isPlatform = tpl.ownership?.source === "platform";
  return (
    <div className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1.5 text-[14.5px]">
      <span style={{ color: C.light }}>归属</span>
      <span className="inline-flex items-center gap-1.5">
        <span className="inline-flex items-center gap-1 text-[13px] px-2 py-0.5 rounded-full font-medium" style={{ color: vis.color, background: vis.bg }}>
          {vis.label === "共享池" ? <Globe className="w-3 h-3" /> : vis.label === "私有" ? <Lock className="w-3 h-3" /> : <ShieldCheck className="w-3 h-3" />}
          {vis.label}
        </span>
        {isPlatform && <span className="text-[13px] px-1.5 py-0.5 rounded" style={{ background: "#F5EDD9", color: "#8A6A1F" }}>官方模板</span>}
        {tpl.ownership?.source && (
          <span className="text-[13px] font-mono" style={{ color: C.light }}>· source={tpl.ownership.source}</span>
        )}
      </span>
      <span style={{ color: C.light }}>版本</span><span style={{ color: C.ink }}>{tpl.current_version}</span>
      <span style={{ color: C.light }}>创建</span>
      <span style={{ color: C.ink }}>{(tpl.created_at || "").replace("T", " ").slice(0, 19) || "—"}</span>
      <span style={{ color: C.light }}>ID</span>
      <span className="font-mono text-[13px] break-all" style={{ color: C.mid }}>—</span>
    </div>
  );
}

function visInfo(v: string | null | undefined) {
  if (v === "platform") return { label: "平台模板", color: "#2E5A4C", bg: "#EAF2EE" };
  if (v === "public") return { label: "共享池", color: "#8A6A1F", bg: "#FBF4E4" };
  return { label: "私有", color: "#5F5E5A", bg: "#F1EFE8" };
}

function TemplateRow({ t, onView, onSubmit }: {
  t: CapabilityTemplate;
  onView: (t: CapabilityTemplate) => void;
  onSubmit: (t: CapabilityTemplate) => void;
}) {
  const vis = visInfo(t.ownership?.visibility);
  const isPlatform = t.ownership?.source === "platform";
  return (
    <tr className="border-b last:border-0 hover:bg-[#F8FAF9]" style={{ borderColor: C.border }}>
      <td className="px-4 py-3">
        <div className="font-medium" style={{ color: C.ink }}>{t.name}</div>
        <div className="text-[13px] font-mono" style={{ color: C.light }}>—</div>
      </td>
      <td className="px-3 py-3">
        <span className="text-[13px] px-2 py-0.5 rounded" style={{ background: C.soft, color: C.primary }}>
          {KIND_LABEL[t.kind] || t.kind}
        </span>
      </td>
      <td className="px-3 py-3" style={{ color: C.mid }}>{t.current_version}</td>
      <td className="px-3 py-3">
        <span className="inline-flex items-center gap-1 text-[13px] px-2 py-0.5 rounded-full font-medium" style={{ color: vis.color, background: vis.bg }}>
          {vis.label === "共享池" ? <Globe className="w-3 h-3" /> : vis.label === "私有" ? <Lock className="w-3 h-3" /> : <ShieldCheck className="w-3 h-3" />}
          {vis.label}
        </span>
        {isPlatform && <span className="ml-1.5 text-[13px] px-1.5 py-0.5 rounded" style={{ background: "#F5EDD9", color: "#8A6A1F" }}>官方</span>}
      </td>
      <td className="px-3 py-3 text-[14px]" style={{ color: C.light }}>
        {(t.created_at || "").slice(0, 10)}
      </td>
      <td className="px-4 py-3 text-right">
        <div className="inline-flex items-center gap-1.5">
          <Button size="sm" variant="outline" className="h-7 text-[14px]" style={{ color: C.mid }}
            onClick={() => onView(t)}>
            <Eye className="w-3.5 h-3.5 mr-1" /> 详情
          </Button>
          {!isPlatform && (
            <Button size="sm" variant="outline" className="h-7 text-[14px]" style={{ color: C.primary }}
              onClick={() => onSubmit(t)}>
              <Send className="w-3.5 h-3.5 mr-1" /> 提交审核
            </Button>
          )}
        </div>
      </td>
    </tr>
  );
}

export default function CapabilityCenter() {
  const [tab, setTab] = useState<"templates" | "reviews">("templates");
  const [templates, setTemplates] = useState<CapabilityTemplate[]>([]);
  const [submissions, setSubmissions] = useState<CapabilitySubmission[]>([]);
  const [loading, setLoading] = useState(true);

  // 运营统计
  const [stats, setStats] = useState<CapabilityStats | null>(null);

  // 新建模板（可视化编辑，不再让运营写 JSON）
  const [createOpen, setCreateOpen] = useState(false);
  const [newName, setNewName] = useState("");
  const [newKind, setNewKind] = useState("script");
  const [newContent, setNewContent] = useState<Record<string, unknown>>(() => defaultContentFor("script"));
  const [creating, setCreating] = useState(false);

  // 详情（查看 / 编辑 双 Tab）
  const [viewTpl, setViewTpl] = useState<CapabilityTemplate | null>(null);
  const [viewTab, setViewTab] = useState<"view" | "edit">("view");
  const [editContent, setEditContent] = useState<Record<string, unknown>>({});
  const [savingEdit, setSavingEdit] = useState(false);
  const [versions, setVersions] = useState<CapabilityVersion[]>([]);
  const [rollbackBusy, setRollbackBusy] = useState(false);

  // 审核
  const [reviewSub, setReviewSub] = useState<CapabilitySubmission | null>(null);
  const [reviewNote, setReviewNote] = useState("");
  const [reviewing, setReviewing] = useState(false);

  const load = async () => {
    setLoading(true);
    const [ts, ss, st] = await Promise.all([
      fetchCapabilityTemplates(),
      fetchCapabilitySubmissions(),
      fetchCapabilityStats(),
    ]);
    setTemplates(ts);
    setSubmissions(ss);
    setStats(st);
    setLoading(false);
  };

  useEffect(() => { load(); }, []);

  // 详情打开时拉取该模板的版本快照列表；切换/回滚后同步编辑区内容
  useEffect(() => {
    if (viewTpl) {
      fetchCapabilityTemplateVersions(viewTpl.id).then((r) => setVersions(r.items));
      setEditContent((viewTpl.content_json as Record<string, unknown>) || {});
    } else {
      setVersions([]);
      setViewTab("view");
    }
  }, [viewTpl]);

  const doSaveEdit = async () => {
    if (!viewTpl) return;
    setSavingEdit(true);
    const r = await updateCapabilityTemplate(viewTpl.id, { content_json: editContent });
    setSavingEdit(false);
    if (r.ok) {
      toast.success("已保存，旧版本已自动存档，可在版本历史回滚");
      setViewTpl((prev) => (prev ? { ...prev, content_json: editContent } : prev));
      const vr = await fetchCapabilityTemplateVersions(viewTpl.id);
      setVersions(vr.items);
      setViewTab("view");
      await load();
    } else {
      toast.error(r.msg || "保存失败");
    }
  };

  const doRollback = async (tag: string) => {
    if (!viewTpl) return;
    setRollbackBusy(true);
    const r = await rollbackCapabilityTemplate(viewTpl.id, tag);
    setRollbackBusy(false);
    if (r.ok && r.data) {
      const d = r.data as { current_version?: string; content_json?: Record<string, unknown> };
      toast.success(`已回滚至 ${tag}`);
      setViewTpl((prev) => prev ? {
        ...prev,
        current_version: d.current_version ?? tag,
        content_json: d.content_json ?? prev.content_json,
      } : prev);
      const vr = await fetchCapabilityTemplateVersions(viewTpl.id);
      setVersions(vr.items);
      await load();
    } else {
      toast.error(r.msg || "回滚失败");
    }
  };

  const doCreate = async () => {
    if (!newName.trim()) { toast.error("请填写模板名称"); return; }
    setCreating(true);
    const r = await createCapabilityTemplate({ name: newName.trim(), kind: newKind, content_json: newContent });
    setCreating(false);
    if (r.ok) {
      toast.success("模板已创建");
      setCreateOpen(false);
      setNewName(""); setNewKind("script"); setNewContent(defaultContentFor("script"));
      await load();
    } else {
      toast.error(r.msg || "创建失败");
    }
  };

  const doSubmit = async (t: CapabilityTemplate) => {
    const r = await submitCapabilityTemplate(t.id);
    if (r.ok) {
      toast.success(`已提交审核：${t.name}`);
      await load();
    } else {
      toast.error(r.msg || "提交失败");
    }
  };

  const doReview = async (approve: boolean) => {
    if (!reviewSub) return;
    setReviewing(true);
    const r = approve
      ? await approveCapabilitySubmission(reviewSub.id, reviewNote)
      : await rejectCapabilitySubmission(reviewSub.id, reviewNote);
    setReviewing(false);
    if (r.ok) {
      toast.success(approve ? "已采纳，模板进入共享池" : "已强下架，模板收回私有");
      setReviewSub(null);
      setReviewNote("");
      await load();
    } else {
      toast.error(r.msg || (approve ? "采纳失败" : "下架失败"));
    }
  };

  const openDetail = (t: CapabilityTemplate) => {
    setViewTab("view");
    setViewTpl(t);
  };

  const pendingCount = submissions.filter((s) => s.status === "PENDING").length;

  return (
    <div className="space-y-4">
      {/* 标题 + 业务定位说明卡 */}
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div className="flex items-center gap-2">
          <Boxes className="w-5 h-5" style={{ color: C.primary }} />
          <span className="text-[17px] font-semibold" style={{ color: C.primary }}>能力中心</span>
          <span className="text-[14px]" style={{ color: C.light }}>多租户能力模板 · 平台↔机构归属全模型</span>
        </div>
        <Button size="sm" style={{ background: C.primary }} onClick={() => { setNewContent(defaultContentFor(newKind)); setCreateOpen(true); }}>
          <FilePlus2 className="w-4 h-4 mr-1" /> 新建模板
        </Button>
      </div>

      {/* 业务定位卡：告诉运营"这页面解决啥问题" */}
      <div className="rounded-lg border p-3 grid grid-cols-1 md:grid-cols-4 gap-2 text-[13.5px]" style={{ borderColor: C.border, background: "#F8FAF9" }}>
        <div className="md:col-span-1 flex items-center gap-2 font-medium" style={{ color: C.ink }}>
          <Info className="w-4 h-4" style={{ color: C.accent }} />
          这页面解决什么
        </div>
        <div className="md:col-span-3" style={{ color: C.mid }}>
          把门店"可复用能力资产"（培训课件 / 穴位知识 / 项目 SOP / 产品培训 / 话术脚本 / 问卷草稿）
          在 <b>平台 ↔ 机构</b> 之间流转——
          <span className="inline-block mx-1 px-1.5 rounded" style={{ background: "#EAF2EE", color: C.primary }}>平台官方</span>
          是共享池基线，机构可克隆自用；
          <span className="inline-block mx-1 px-1.5 rounded" style={{ background: "#F1EFE8", color: "#5F5E5A" }}>机构自建</span>
          默认私有，可提交平台审核——采纳即入共享池、驳回即被强收回私有。
        </div>
      </div>

      {/* 运营统计卡片 */}
      {stats && (
        <div className="rounded-lg border p-3" style={{ borderColor: C.border, background: "#F8FAF9" }}>
          <div className="flex items-center gap-2 mb-2 text-[14px] font-medium" style={{ color: C.ink }}>
            <BarChart3 className="w-4 h-4" style={{ color: C.accent }} /> 运营统计（能力中心全景）
          </div>
          <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-2">
            <StatTile label="模板总数" value={stats.totals.templates} />
            <StatTile label="版本快照" value={stats.totals.versions} />
            <StatTile label="克隆副本" value={stats.totals.clones} />
            <StatTile label="审核·待审" value={stats.reviews.PENDING || 0} tone="warn" />
            <StatTile label="同步·下发" value={stats.sync.push || 0} />
            <StatTile label="同步·贡献" value={stats.sync.contribute || 0} />
          </div>
          <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-[13px]" style={{ color: C.light }}>
            <span>审核：已采纳 {stats.reviews.APPROVED || 0} · 已驳回 {stats.reviews.REJECTED || 0}</span>
            <span>关插件申请：待审 {stats.disable_requests.PENDING || 0} · 已批 {stats.disable_requests.APPROVED || 0} · 已拒 {stats.disable_requests.REJECTED || 0}</span>
          </div>
        </div>
      )}

      {/* Tabs */}
      <div className="flex gap-1 border-b pb-2" style={{ borderColor: C.border }}>
        <button
          className="px-3 py-1.5 rounded-t-md text-[15px] font-medium transition-colors"
          style={{ color: tab === "templates" ? C.primary : C.light, background: tab === "templates" ? C.soft : "transparent", borderBottom: tab === "templates" ? `2px solid ${C.primary}` : "2px solid transparent" }}
          onClick={() => setTab("templates")}
        >
          模板市场（{templates.length}）
        </button>
        <button
          className="px-3 py-1.5 rounded-t-md text-[15px] font-medium transition-colors"
          style={{ color: tab === "reviews" ? C.primary : C.light, background: tab === "reviews" ? C.soft : "transparent", borderBottom: tab === "reviews" ? `2px solid ${C.primary}` : "2px solid transparent" }}
          onClick={() => setTab("reviews")}
        >
          审核工作台
          {pendingCount > 0 && (
            <span className="ml-1.5 text-[13px] px-1.5 py-0.5 rounded-full" style={{ background: "#FDECEA", color: "#B03A2E" }}>{pendingCount}</span>
          )}
        </button>
      </div>

      {loading && (
        <div className="flex items-center gap-2 text-[15px]" style={{ color: C.light }}>
          <Loader2 className="w-4 h-4 animate-spin" /> 加载能力中心…
        </div>
      )}

      {/* ─── Tab 1: 模板市场 ─── */}
      {tab === "templates" && !loading && (
        <Card className="border shadow-none" style={{ borderColor: C.border }}>
          <CardContent className="p-0">
            <table className="w-full text-[15px]">
              <thead>
                <tr className="border-b text-left" style={{ borderColor: C.border, background: C.soft }}>
                  <th className="px-4 py-3 text-[14px] font-semibold whitespace-nowrap" style={{ color: C.mid }}>模板</th>
                  <th className="px-3 py-3 text-[14px] font-semibold whitespace-nowrap" style={{ color: C.mid }}>类型</th>
                  <th className="px-3 py-3 text-[14px] font-semibold whitespace-nowrap" style={{ color: C.mid }}>版本</th>
                  <th className="px-3 py-3 text-[14px] font-semibold whitespace-nowrap" style={{ color: C.mid }}>归属</th>
                  <th className="px-3 py-3 text-[14px] font-semibold whitespace-nowrap" style={{ color: C.mid }}>创建时间</th>
                  <th className="px-4 py-3 text-right text-[14px] font-semibold whitespace-nowrap" style={{ color: C.mid }}>操作</th>
                </tr>
              </thead>
              <tbody>
                {templates.map((t) => (
                  <TemplateRow key={t.id} t={t} onView={openDetail} onSubmit={doSubmit} />
                ))}
                {templates.length === 0 && (
                  <tr><td colSpan={6} className="py-10 text-center text-[14px]" style={{ color: C.light }}>暂无模板</td></tr>
                )}
              </tbody>
            </table>
          </CardContent>
        </Card>
      )}

      {/* ─── Tab 2: 审核工作台 ─── */}
      {tab === "reviews" && !loading && (
        <Card className="border shadow-none" style={{ borderColor: C.border }}>
          <CardContent className="p-0">
            <table className="w-full text-[15px]">
              <thead>
                <tr className="border-b text-left" style={{ borderColor: C.border, background: C.soft }}>
                  <th className="px-4 py-3 text-[14px] font-semibold" style={{ color: C.mid }}>审核单</th>
                  <th className="px-3 py-3 text-[14px] font-semibold" style={{ color: C.mid }}>提交机构</th>
                  <th className="px-3 py-3 text-[14px] font-semibold" style={{ color: C.mid }}>状态</th>
                  <th className="px-3 py-3 text-[14px] font-semibold" style={{ color: C.mid }}>提交时间</th>
                  <th className="px-3 py-3 text-[14px] font-semibold" style={{ color: C.mid }}>审核意见</th>
                  <th className="px-4 py-3 text-right text-[14px] font-semibold" style={{ color: C.mid }}>操作</th>
                </tr>
              </thead>
              <tbody>
                {submissions.map((s, si) => {
                  const tpl = templates.find((t) => t.id === s.template_id);
                  const st = s.status === "PENDING" ? { label: "待审核", color: "#8A6A1F", bg: "#FBF4E4" }
                    : s.status === "APPROVED" ? { label: "已采纳", color: "#2E5A4C", bg: "#EAF2EE" }
                    : { label: "已驳回", color: "#B03A2E", bg: "#FDECEA" };
                  return (
                    <tr key={s.id} className="border-b last:border-0 hover:bg-[#F8FAF9]" style={{ borderColor: C.border }}>
                      <td className="px-4 py-3">
                        <div className="font-medium" style={{ color: C.ink }}>{tpl?.name || "—"}</div>
                        <div className="text-[13px] font-mono" style={{ color: C.light }} title={s.id}>#{si + 1}</div>
                      </td>
                      <td className="px-3 py-3" style={{ color: C.mid }}>{s.submitter_org_id || "—"}</td>
                      <td className="px-3 py-3">
                        <span className="text-[13px] px-2 py-0.5 rounded-full font-medium" style={{ color: st.color, background: st.bg }}>{st.label}</span>
                      </td>
                      <td className="px-3 py-3 text-[14px]" style={{ color: C.light }}>{(s.submitted_at || "").replace("T", " ").slice(0, 16)}</td>
                      <td className="px-3 py-3 text-[14px] max-w-[160px] truncate" style={{ color: C.light }} title={s.review_note || ""}>{s.review_note || "—"}</td>
                      <td className="px-4 py-3 text-right">
                        {s.status === "PENDING" ? (
                          <Button size="sm" variant="outline" className="h-7 text-[14px]" style={{ color: C.primary }}
                            onClick={() => { setReviewSub(s); setReviewNote(""); }}>
                            <ShieldCheck className="w-3.5 h-3.5 mr-1" /> 审核
                          </Button>
                        ) : (
                          <span className="text-[13px]" style={{ color: C.light }}>
                            {s.reviewed_at ? s.reviewed_at.replace("T", " ").slice(0, 16) : "—"}
                          </span>
                        )}
                      </td>
                    </tr>
                  );
                })}
                {submissions.length === 0 && (
                  <tr><td colSpan={6} className="py-10 text-center text-[14px]" style={{ color: C.light }}>暂无审核单</td></tr>
                )}
              </tbody>
            </table>
          </CardContent>
        </Card>
      )}

      <div className="text-[13px]" style={{ color: C.light }}>
        归属模型：平台模板（source=platform）全网可见；机构自建（private）仅本机构；提交平台审核通过后提升为共享池（public），驳回则强收回私有。
      </div>

      {/* 新建模板（可视化编辑） */}
      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent className="max-w-3xl max-h-[88vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>新建能力模板</DialogTitle>
            <DialogDescription>像填表一样填写内容；也可以先从 Word / 文本文件导入，再修改。提交审核通过后进入共享池。</DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label className="text-[14px]">名称</Label>
                <Input value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="如：门店接单话术模板" className="mt-1 h-8" />
              </div>
              <div>
                <Label className="text-[14px]">类型</Label>
                <select value={newKind}
                  onChange={(e) => { setNewKind(e.target.value); setNewContent(defaultContentFor(e.target.value)); }}
                  className="w-full text-[15px] rounded-lg border px-3 py-2 bg-white outline-none mt-1" style={{ borderColor: C.border }}>
                  <option value="script">话术脚本</option>
                  <option value="knowledge">知识课件</option>
                  <option value="project">项目培训</option>
                  <option value="product">产品培训</option>
                  <option value="questionnaire">问卷草稿</option>
                  <option value="herb">中药</option>
                  <option value="formula">方剂</option>
                  <option value="syndrome">证候</option>
                  <option value="disease">疾病</option>
                  <option value="other">其他</option>
                </select>
              </div>
            </div>
            <TextImporter kind={newKind} onImport={(parsed) => setNewContent(parsed)} />
            <div className="rounded-md border p-3" style={{ borderColor: C.border, background: "#fff" }}>
              <div className="text-[14px] font-medium mb-2 flex items-center gap-1" style={{ color: C.mid }}>
                <Sparkles className="w-3.5 h-3.5" style={{ color: C.accent }} />
                内容编辑
              </div>
              <TemplateEditor kind={newKind} value={newContent} onChange={setNewContent} />
            </div>
          </div>
          <DialogFooter>
            <Button size="sm" variant="outline" onClick={() => setCreateOpen(false)}>取消</Button>
            <Button size="sm" style={{ background: C.primary }} disabled={creating} onClick={doCreate}>
              {creating && <Loader2 className="w-3.5 h-3.5 mr-1 animate-spin" />}创建
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* 模板详情（查看 / 编辑） */}
      <Dialog open={!!viewTpl} onOpenChange={(o) => { if (!o) setViewTpl(null); }}>
        <DialogContent className="max-w-3xl max-h-[88vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Eye className="w-4 h-4" style={{ color: C.primary }} />
              模板详情 · {viewTpl?.name}
            </DialogTitle>
            <DialogDescription>
              {viewTpl?.kind && (
                <span className="text-[13px] px-1.5 py-0.5 rounded mr-1.5" style={{ background: C.soft, color: C.primary }}>
                  {KIND_LABEL[viewTpl.kind] || viewTpl.kind}
                </span>
              )}
              <span>查看效果或直接编辑内容；编辑保存后旧版本自动存档，可回滚</span>
            </DialogDescription>
          </DialogHeader>
          {viewTpl && (
            <div className="space-y-3">
              <div className="rounded-md p-2.5" style={{ background: "#F8FAF9", border: `1px solid ${C.border}` }}>
                <TemplateMeta tpl={viewTpl} />
              </div>

              {/* 查看 / 编辑 Tab */}
              <div className="flex gap-1.5">
                <button type="button"
                  onClick={() => setViewTab("view")}
                  className="inline-flex items-center gap-1 text-[14px] px-3 py-1.5 rounded-full border transition-colors"
                  style={viewTab === "view"
                    ? { background: C.primary, color: "#fff", borderColor: C.primary }
                    : { background: "#fff", color: C.mid, borderColor: C.border }}>
                  <Eye className="w-3.5 h-3.5" />查看
                </button>
                <button type="button"
                  onClick={() => { setEditContent((viewTpl.content_json as Record<string, unknown>) || {}); setViewTab("edit"); }}
                  className="inline-flex items-center gap-1 text-[14px] px-3 py-1.5 rounded-full border transition-colors"
                  style={viewTab === "edit"
                    ? { background: C.primary, color: "#fff", borderColor: C.primary }
                    : { background: "#fff", color: C.mid, borderColor: C.border }}>
                  <Pencil className="w-3.5 h-3.5" />编辑
                </button>
              </div>

              {viewTab === "view" && (
              <div>
                <div className="flex items-center justify-between mb-1.5">
                  <div className="text-[14px] font-medium flex items-center gap-1" style={{ color: C.mid }}>
                    <Sparkles className="w-3.5 h-3.5" style={{ color: C.accent }} />
                    内容（{viewTpl.kind === "knowledge" ? "课件知识切片" :
                          viewTpl.kind === "project" ? "项目 SOP" :
                          viewTpl.kind === "product" ? "产品培训" :
                          viewTpl.kind === "script" ? "话术脚本" :
                          viewTpl.kind === "herb" || viewTpl.kind === "formula" || viewTpl.kind === "syndrome" ? "知识图谱·智能体引用" :
                          "结构化模板"}）
                  </div>
                </div>
                <div className="rounded-md border p-2.5 max-h-[420px] overflow-auto" style={{ borderColor: C.border }}>
                  <TemplatePreview content={(viewTpl.content_json as Record<string, unknown>) || {}} />
                </div>
              </div>
              )}

              {viewTab === "edit" && (
              <div className="space-y-2.5">
                <TextImporter kind={viewTpl.kind} onImport={(parsed) => setEditContent(parsed)} />
                <div className="rounded-md border p-3" style={{ borderColor: C.border, background: "#fff" }}>
                  <TemplateEditor kind={viewTpl.kind} value={editContent} onChange={setEditContent} />
                </div>
                <div className="flex items-center gap-2">
                  <Button size="sm" style={{ background: C.primary }} disabled={savingEdit} onClick={doSaveEdit}>
                    {savingEdit && <Loader2 className="w-3.5 h-3.5 mr-1 animate-spin" />}保存修改
                  </Button>
                  <Button size="sm" variant="outline" onClick={() => setViewTab("view")}>取消编辑</Button>
                  <span className="text-[13px]" style={{ color: C.light }}>保存会生成新版本，旧内容可在「版本历史」回滚</span>
                </div>
              </div>
              )}

              {/* 版本历史 */}
              <div>
                <div className="flex items-center justify-between mb-1.5">
                  <div className="text-[14px] font-medium flex items-center gap-1" style={{ color: C.mid }}>
                    <History className="w-3.5 h-3.5" style={{ color: C.accent }} />
                    版本历史（{versions.length}）
                  </div>
                </div>
                <div className="rounded-md border p-2.5 max-h-[260px] overflow-auto space-y-1.5" style={{ borderColor: C.border }}>
                  {versions.length === 0 && (
                    <div className="text-[13.5px]" style={{ color: C.light }}>暂无历史版本（至少编辑一次才会生成快照）</div>
                  )}
                  {versions.map((v) => {
                    const isCurrent = v.version_tag === viewTpl?.current_version;
                    return (
                      <div key={v.version_tag} className="flex items-center justify-between gap-2 rounded-md px-2.5 py-2" style={{ border: `1px solid ${C.border}`, background: isCurrent ? "#EAF2EE" : "#FCFCFA" }}>
                        <div className="min-w-0">
                          <div className="flex items-center gap-1.5">
                            <span className="text-[14.5px] font-semibold" style={{ color: C.ink }}>{v.version_tag}</span>
                            {isCurrent && <span className="text-[12px] px-1.5 py-0.5 rounded-full" style={{ background: C.primary, color: "#fff" }}>当前</span>}
                          </div>
                          <div className="text-[13px]" style={{ color: C.light }}>
                            {(v.created_at || "").replace("T", " ").slice(0, 19) || "—"}
                          </div>
                        </div>
                        <Button size="sm" variant="outline" className="h-7 text-[14px]" style={{ color: C.primary }}
                          disabled={isCurrent || rollbackBusy}
                          onClick={() => doRollback(v.version_tag)}>
                          <Undo2 className="w-3.5 h-3.5 mr-1" /> 回滚
                        </Button>
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>
          )}
          <DialogFooter>
            <Button size="sm" variant="outline" onClick={() => setViewTpl(null)}>关闭</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* 审核弹窗 */}
      <Dialog open={!!reviewSub} onOpenChange={(o) => { if (!o) setReviewSub(null); }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>审核模板提交</DialogTitle>
            <DialogDescription>
              {(() => {
                const tpl = reviewSub ? templates.find((t) => t.id === reviewSub.template_id) : null;
                return tpl ? `「${tpl.name}」提交自 ${reviewSub?.submitter_org_id || "—"}。采纳=进入共享池；驳回=强收回私有。` : "模板提交审核";
              })()}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <Label className="text-[14px]">审核意见</Label>
            <textarea value={reviewNote} onChange={(e) => setReviewNote(e.target.value)}
              placeholder="填写采纳/驳回理由（必填）"
              className="w-full text-[14px] rounded-lg border p-2 outline-none h-20" style={{ borderColor: C.border }} />
          </div>
          <DialogFooter className="gap-2">
            <Button size="sm" variant="outline" onClick={() => setReviewSub(null)}>取消</Button>
            <Button size="sm" style={{ background: "#B03A2E" }} disabled={reviewing || !reviewNote.trim()} onClick={() => doReview(false)}>
              {reviewing ? <Loader2 className="w-3.5 h-3.5 mr-1 animate-spin" /> : <XCircle className="w-3.5 h-3.5 mr-1" />}驳回
            </Button>
            <Button size="sm" style={{ background: C.primary }} disabled={reviewing || !reviewNote.trim()} onClick={() => doReview(true)}>
              {reviewing ? <Loader2 className="w-3.5 h-3.5 mr-1 animate-spin" /> : <CheckCircle2 className="w-3.5 h-3.5 mr-1" />}采纳
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}