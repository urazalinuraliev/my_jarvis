"use client";

import {
  Suspense,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import {
  WorkflowMeta,
  WorkflowRunSummary,
  WorkflowSection,
  deleteCustomWorkflow,
  deleteWorkflowRun,
  listWorkflowRuns,
  listWorkflows,
} from "@/lib/api";

const SECTION_ORDER: WorkflowSection[] = [
  "Board",
  "Capital & Investors",
  "Growth & GTM",
  "Product",
  "People",
  "Risk, Legal & Crisis",
  "Operating Cadence",
];

const SECTION_BLURB: Record<WorkflowSection, string> = {
  Board: "Decks, memos, and talking points for your board meetings.",
  "Capital & Investors":
    "Materials for raising capital and reporting to investors.",
  "Growth & GTM":
    "Positioning, launches, pricing, and competitive plays.",
  Product: "Strategy memos, retention and product decisions.",
  People: "Hiring, performance, org design, and compensation.",
  "Risk, Legal & Crisis":
    "Risk register, M&A diligence, and crisis-comms preparation.",
  "Operating Cadence":
    "The monthly, quarterly, and annual rhythm of running the company.",
};

type Tab = "catalog" | "runs";
type RunStatus = "active" | "done" | "error";

function isTab(v: string | null): v is Tab {
  return v === "catalog" || v === "runs";
}
function isStatus(v: string | null): v is RunStatus {
  return v === "active" || v === "done" || v === "error";
}

function formatRelativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

function statusBadge(status: string) {
  const color =
    status === "done"
      ? "bg-emerald-500/10 text-emerald-400 ring-emerald-500/30"
      : status === "error"
      ? "bg-red-500/10 text-red-400 ring-red-500/30"
      : "bg-amber-500/10 text-amber-400 ring-amber-500/30";
  return (
    <span
      className={`inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium ring-1 ${color}`}
    >
      {status}
    </span>
  );
}

function matchesQuery(q: string, ...fields: (string | undefined)[]): boolean {
  if (!q) return true;
  const needle = q.toLowerCase();
  return fields.some((f) => (f ?? "").toLowerCase().includes(needle));
}

function groupBy<T, K extends string>(
  arr: T[],
  keyFn: (item: T) => K
): Map<K, T[]> {
  const out = new Map<K, T[]>();
  for (const item of arr) {
    const k = keyFn(item);
    const bucket = out.get(k);
    if (bucket) bucket.push(item);
    else out.set(k, [item]);
  }
  return out;
}

function runStatusBucket(s: WorkflowRunSummary["status"]): RunStatus {
  if (s === "running") return "active";
  if (s === "done" || s === "error") return s;
  // Defensive: unknown future statuses surface under Active so they're not lost.
  return "active";
}

function JobsPageInner() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const tab: Tab = isTab(searchParams.get("tab"))
    ? (searchParams.get("tab") as Tab)
    : "catalog";
  const statusParam = searchParams.get("status");
  const status: RunStatus | null = isStatus(statusParam) ? statusParam : null;

  const [workflows, setWorkflows] = useState<WorkflowMeta[]>([]);
  const [runs, setRuns] = useState<WorkflowRunSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [catalogQuery, setCatalogQuery] = useState("");
  const [runsQuery, setRunsQuery] = useState("");
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});

  const refresh = useCallback(async () => {
    setError(null);
    try {
      const [wfs, rs] = await Promise.all([listWorkflows(), listWorkflowRuns()]);
      setWorkflows(wfs);
      setRuns(rs);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const setParam = useCallback(
    (updates: Record<string, string | null>) => {
      const sp = new URLSearchParams(searchParams.toString());
      for (const [k, v] of Object.entries(updates)) {
        if (v === null) sp.delete(k);
        else sp.set(k, v);
      }
      const qs = sp.toString();
      router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
    },
    [pathname, router, searchParams]
  );

  const runCounts = useMemo(() => {
    const c = { active: 0, done: 0, error: 0 };
    for (const r of runs) c[runStatusBucket(r.status)]++;
    return c;
  }, [runs]);

  // Default the runs sub-tab once data is loaded and ?status is missing/invalid.
  // Ref guard ensures we only auto-set on the first eligible render, so a user
  // who explicitly navigates back to ?tab=runs without ?status isn't overridden
  // mid-interaction and StrictMode double-invocation doesn't double-write.
  const defaultedStatusRef = useRef(false);
  useEffect(() => {
    if (tab !== "runs" || loading) return;
    if (status !== null) return;
    if (defaultedStatusRef.current) return;
    defaultedStatusRef.current = true;
    const next: RunStatus = runCounts.active > 0 ? "active" : "done";
    setParam({ status: next });
  }, [tab, loading, status, runCounts.active, setParam]);

  const workflowTitleMap = useMemo(
    () => new Map(workflows.map((w) => [w.name, w.title] as const)),
    [workflows]
  );

  const handleDelete = useCallback(
    async (runId: string) => {
      if (!confirm("Delete this run?")) return;
      await deleteWorkflowRun(runId);
      refresh();
    },
    [refresh]
  );

  const handleDeleteCustom = useCallback(
    async (name: string) => {
      if (!confirm(`Delete the custom workflow “${name}”? This cannot be undone.`))
        return;
      await deleteCustomWorkflow(name);
      refresh();
    },
    [refresh]
  );

  return (
    <>
      <div className="flex items-center gap-1 border-b border-line mb-6">
            <TabButton
              active={tab === "catalog"}
              onClick={() => setParam({ tab: "catalog" })}
              label="Catalog"
              count={workflows.length}
            />
            <TabButton
              active={tab === "runs"}
              onClick={() => setParam({ tab: "runs" })}
              label="Runs"
              count={runs.length}
            />
          </div>

          {loading && (
            <div className="text-sm text-fg-muted">Loading jobs…</div>
          )}
          {error && (
            <div className="text-sm text-red-400 mb-4">Error: {error}</div>
          )}

          {!loading && tab === "catalog" && (
            <CatalogView
              workflows={workflows}
              query={catalogQuery}
              onQueryChange={setCatalogQuery}
              onDeleteCustom={handleDeleteCustom}
            />
          )}

          {!loading && tab === "runs" && (
            <RunsView
              runs={runs}
              counts={runCounts}
              status={status ?? "active"}
              onStatusChange={(s) => setParam({ status: s })}
              query={runsQuery}
              onQueryChange={setRunsQuery}
              workflowTitleMap={workflowTitleMap}
              collapsed={collapsed}
              onToggleCollapsed={(key) =>
                setCollapsed((c) => ({ ...c, [key]: !c[key] }))
              }
              onDelete={handleDelete}
            />
          )}
    </>
  );
}

function TabButton({
  active,
  onClick,
  label,
  count,
}: {
  active: boolean;
  onClick: () => void;
  label: string;
  count: number;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`-mb-px px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
        active
          ? "border-indigo-500 text-fg"
          : "border-transparent text-fg-muted hover:text-fg"
      }`}
    >
      {label}
      <span className="ml-2 text-xs text-fg-muted">{count}</span>
    </button>
  );
}

function SearchInput({
  value,
  onChange,
  placeholder,
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder: string;
}) {
  return (
    <input
      type="search"
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
      className="w-full sm:w-80 px-3 py-1.5 text-sm rounded-md bg-surface/60 border border-line text-fg placeholder:text-fg-subtle focus:outline-none focus:ring-1 focus:ring-indigo-500/40 focus:border-line-strong"
    />
  );
}

function CatalogView({
  workflows,
  query,
  onQueryChange,
  onDeleteCustom,
}: {
  workflows: WorkflowMeta[];
  query: string;
  onQueryChange: (v: string) => void;
  onDeleteCustom: (name: string) => void;
}) {
  const filtered = workflows.filter((w) =>
    matchesQuery(query, w.title, w.description)
  );

  // User-created workflows are grouped together under "Custom" regardless of
  // their declared section, so they're easy to find, edit, and delete.
  const custom = filtered.filter((w) => w.is_custom);
  const builtin = filtered.filter((w) => !w.is_custom);
  const known = new Set<string>(SECTION_ORDER);
  const others = builtin.filter((w) => !known.has(w.section));

  const renderCard = (w: WorkflowMeta) => (
    <Link
      key={w.name}
      href={`/jobs/${encodeURIComponent(w.name)}`}
      className="block rounded-lg border border-line bg-surface/40 hover:border-line-strong hover:bg-surface-elevated/40 p-5 transition"
    >
      <h3 className="text-base font-semibold text-fg mb-2">{w.title}</h3>
      <p className="text-sm text-fg-muted leading-relaxed mb-3">
        {w.description}
      </p>
      <div className="flex items-center justify-between text-xs text-fg-muted">
        <span>{w.steps.length} steps</span>
        <span>~{w.estimated_minutes} min</span>
      </div>
    </Link>
  );

  const renderCustomCard = (w: WorkflowMeta) => (
    <div
      key={w.name}
      className="rounded-lg border border-line bg-surface/40 p-5 transition hover:border-line-strong"
    >
      <Link href={`/jobs/${encodeURIComponent(w.name)}`} className="block">
        <h3 className="text-base font-semibold text-fg mb-2">{w.title}</h3>
        <p className="text-sm text-fg-muted leading-relaxed mb-3">
          {w.description}
        </p>
        <div className="flex items-center justify-between text-xs text-fg-muted">
          <span>{w.steps.length} steps</span>
          <span>~{w.estimated_minutes} min</span>
        </div>
      </Link>
      <div className="mt-3 flex items-center gap-3 border-t border-line pt-3 text-xs">
        <Link
          href={`/jobs/new?edit=${encodeURIComponent(w.name)}`}
          className="text-indigo-400 hover:text-indigo-300"
        >
          Edit
        </Link>
        <button
          type="button"
          onClick={() => onDeleteCustom(w.name)}
          className="text-fg-muted hover:text-red-400 transition"
        >
          Delete
        </button>
      </div>
    </div>
  );

  const renderSection = (
    section: string,
    blurb: string,
    items: WorkflowMeta[],
    card: (w: WorkflowMeta) => React.ReactNode = renderCard
  ) => (
    <div key={section}>
      <div className="mb-3 flex items-baseline gap-3">
        <h2 className="text-base font-semibold text-fg">{section}</h2>
        <span className="text-xs text-fg-muted">
          {items.length} {items.length === 1 ? "job" : "jobs"}
        </span>
      </div>
      <p className="text-xs text-fg-muted mb-3 leading-relaxed">{blurb}</p>
      <div className="grid sm:grid-cols-2 gap-4">{items.map(card)}</div>
    </div>
  );

  return (
    <div>
      <div className="mb-6 flex items-center justify-between gap-4">
        <SearchInput
          value={query}
          onChange={onQueryChange}
          placeholder="Search workflows by title or description…"
        />
        <Link
          href="/jobs/new"
          className="shrink-0 rounded-md bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-500 transition"
        >
          + New workflow
        </Link>
      </div>

      {workflows.length === 0 ? (
        <div className="text-sm text-fg-muted">No jobs registered yet.</div>
      ) : filtered.length === 0 ? (
        <div className="text-sm text-fg-muted">
          No jobs match &ldquo;{query}&rdquo;.
        </div>
      ) : (
        <div className="space-y-10">
          {custom.length > 0 &&
            renderSection(
              "Custom",
              "Workflows you created. Edit or delete them anytime.",
              custom,
              renderCustomCard
            )}
          {SECTION_ORDER.map((section) => {
            const items = builtin.filter((w) => w.section === section);
            if (items.length === 0) return null;
            return renderSection(section, SECTION_BLURB[section], items);
          })}
          {others.length > 0 &&
            renderSection(
              "Other",
              "Workflows not yet assigned to a known section.",
              others
            )}
        </div>
      )}
    </div>
  );
}

function RunsView({
  runs,
  counts,
  status,
  onStatusChange,
  query,
  onQueryChange,
  workflowTitleMap,
  collapsed,
  onToggleCollapsed,
  onDelete,
}: {
  runs: WorkflowRunSummary[];
  counts: Record<RunStatus, number>;
  status: RunStatus;
  onStatusChange: (s: RunStatus) => void;
  query: string;
  onQueryChange: (v: string) => void;
  workflowTitleMap: Map<string, string>;
  collapsed: Record<string, boolean>;
  onToggleCollapsed: (key: string) => void;
  onDelete: (runId: string) => void;
}) {
  const visible = runs.filter(
    (r) =>
      runStatusBucket(r.status) === status &&
      matchesQuery(query, r.title, r.workflow_name)
  );

  const groups = useMemo(
    () => groupBy(visible, (r) => r.workflow_name),
    [visible]
  );

  const emptyMsg =
    status === "active"
      ? "No active runs."
      : status === "done"
      ? "No completed runs yet."
      : "No errors.";

  return (
    <div>
      <div className="flex items-center gap-1 mb-4">
        <StatusSegment
          active={status === "active"}
          onClick={() => onStatusChange("active")}
          label="Active"
          count={counts.active}
          tone="amber"
        />
        <StatusSegment
          active={status === "done"}
          onClick={() => onStatusChange("done")}
          label="Done"
          count={counts.done}
          tone="emerald"
        />
        <StatusSegment
          active={status === "error"}
          onClick={() => onStatusChange("error")}
          label="Error"
          count={counts.error}
          tone="red"
        />
      </div>

      <div className="mb-4">
        <SearchInput
          value={query}
          onChange={onQueryChange}
          placeholder="Search runs by title or workflow…"
        />
      </div>

      {visible.length === 0 ? (
        <div className="text-sm text-fg-muted">
          {query ? `No runs match “${query}”.` : emptyMsg}
        </div>
      ) : (
        <div className="space-y-5">
          {Array.from(groups.entries()).map(([workflowName, items]) => {
            const title = workflowTitleMap.get(workflowName) ?? workflowName;
            const isCollapsed = !!collapsed[workflowName];
            return (
              <div key={workflowName}>
                <button
                  type="button"
                  onClick={() => onToggleCollapsed(workflowName)}
                  className="w-full flex items-center gap-2 mb-2 text-left"
                >
                  <span
                    className={`text-fg-muted text-xs transition-transform ${
                      isCollapsed ? "" : "rotate-90"
                    }`}
                  >
                    ▶
                  </span>
                  <span className="text-sm font-semibold text-fg">
                    {title}
                  </span>
                  <span className="text-xs text-fg-muted">
                    {items.length} {items.length === 1 ? "run" : "runs"}
                  </span>
                </button>
                {!isCollapsed && (
                  <div className="space-y-2">
                    {items.map((r) => (
                      <div
                        key={r.run_id}
                        className="flex items-center justify-between gap-4 rounded-md border border-line bg-surface/30 px-4 py-3"
                      >
                        <Link
                          href={`/jobs/runs/${encodeURIComponent(r.run_id)}`}
                          className="flex-1 min-w-0"
                        >
                          <div className="flex items-center gap-2 mb-1">
                            <span className="text-sm font-medium text-fg truncate">
                              {r.title}
                            </span>
                            {statusBadge(r.status)}
                          </div>
                          <div className="text-xs text-fg-muted">
                            updated {formatRelativeTime(r.updated_at)}
                          </div>
                        </Link>
                        <button
                          type="button"
                          onClick={() => onDelete(r.run_id)}
                          className="text-xs text-fg-muted hover:text-red-400 transition"
                          aria-label="Delete run"
                        >
                          Delete
                        </button>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function StatusSegment({
  active,
  onClick,
  label,
  count,
  tone,
}: {
  active: boolean;
  onClick: () => void;
  label: string;
  count: number;
  tone: "amber" | "emerald" | "red";
}) {
  const toneRing =
    tone === "amber"
      ? "ring-amber-500/40 text-amber-300"
      : tone === "emerald"
      ? "ring-emerald-500/40 text-emerald-300"
      : "ring-red-500/40 text-red-300";
  return (
    <button
      type="button"
      onClick={onClick}
      className={`px-3 py-1.5 text-xs rounded-md ring-1 transition ${
        active
          ? `bg-surface-elevated ${toneRing}`
          : "ring-line text-fg-muted hover:text-fg hover:ring-line-strong"
      }`}
    >
      {label}
      <span className="ml-1.5 text-fg-muted">{count}</span>
    </button>
  );
}

export default function JobsPage() {
  return (
    <div className="flex flex-col h-full bg-surface text-fg">
      <main className="flex-1 overflow-y-auto px-6 py-8">
        <div className="max-w-5xl mx-auto">
          <div className="mb-6">
            <h1 className="text-2xl font-semibold text-fg mb-1">
              Executive Jobs
            </h1>
            <p className="text-sm text-fg-muted">
              Structured executive workflows that produce a deliverable — not a
              conversation. Each job orchestrates the relevant specialists and
              knowledge to draft a complete artifact.
            </p>
          </div>
          <Suspense fallback={null}>
            <JobsPageInner />
          </Suspense>
        </div>
      </main>
    </div>
  );
}
