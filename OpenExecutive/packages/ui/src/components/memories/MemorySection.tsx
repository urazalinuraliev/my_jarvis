"use client";

import { useCallback, useEffect, useState } from "react";
import {
  deleteAdvice,
  deleteDecision,
  deleteInitiative,
  listAdvice,
  listDecisions,
  listInitiatives,
  updateAdvice,
  updateDecision,
  updateInitiative,
  type Advice,
  type Decision,
  type Initiative,
} from "@/lib/api";
import { DOMAINS, STATUSES, EmptyState, formatDate } from "./shared";

type MemoryTab = "decisions" | "initiatives" | "advice";

const MEMORY_EMPTY = "No memories yet — they're extracted automatically after chats.";

// ---------------------------------------------------------------------------
// Section shell — the "what it knows" half of the Pulse page.
// ---------------------------------------------------------------------------

export default function MemorySection() {
  const [tab, setTab] = useState<MemoryTab>("decisions");
  // Each tab reports its row count so the tab labels can carry a live badge.
  // All three tabs stay mounted (inactive ones hidden) so every count loads up
  // front; a tab's own edit/delete re-runs its refresh, which reports the new
  // length back here, keeping that tab's badge correct.
  const [counts, setCounts] = useState<Record<MemoryTab, number | null>>({
    decisions: null,
    initiatives: null,
    advice: null,
  });
  // Stable per-tab callbacks — these are passed to the (always-mounted) tabs as
  // `onCount`, which lives in each tab's `refresh` useCallback deps. They MUST
  // keep a constant identity across renders, or the tab's refresh→useEffect
  // chain would re-fire every render and loop forever. (Do NOT inline a
  // `setCount(tab)` factory here.)
  const onCountDecisions = useCallback((n: number) => setCounts((c) => ({ ...c, decisions: n })), []);
  const onCountInitiatives = useCallback((n: number) => setCounts((c) => ({ ...c, initiatives: n })), []);
  const onCountAdvice = useCallback((n: number) => setCounts((c) => ({ ...c, advice: n })), []);

  return (
    <div className="rounded-xl border border-line bg-surface-elevated p-4">
      <div className="mb-3">
        <div className="flex gap-1 p-1 bg-surface-overlay/60 rounded-xl w-fit border border-line-strong/50">
          {(["decisions", "initiatives", "advice"] as MemoryTab[]).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`px-4 py-1.5 rounded-lg text-sm font-medium transition-colors capitalize ${
                tab === t
                  ? "bg-surface-input text-fg shadow-sm"
                  : "text-fg-muted hover:text-fg"
              }`}
            >
              {t}
              {counts[t] != null && (
                <span className="ml-1.5 text-xs font-normal tabular-nums text-fg-subtle">
                  {counts[t]}
                </span>
              )}
            </button>
          ))}
        </div>
      </div>

      {/* One scroll region shared by all three (always-mounted) tabs, mirroring
          the Recent activity card — the list scrolls instead of growing. */}
      <div className="max-h-[32rem] overflow-y-auto pr-1">
        <div className={tab === "decisions" ? "" : "hidden"}>
          <DecisionsTab onCount={onCountDecisions} />
        </div>
        <div className={tab === "initiatives" ? "" : "hidden"}>
          <InitiativesTab onCount={onCountInitiatives} />
        </div>
        <div className={tab === "advice" ? "" : "hidden"}>
          <AdviceTab onCount={onCountAdvice} />
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Decisions
// ---------------------------------------------------------------------------

function DecisionsTab({ onCount }: { onCount: (n: number) => void }) {
  const [items, setItems] = useState<Decision[]>([]);
  const [loading, setLoading] = useState(true);
  const [editingId, setEditingId] = useState<number | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const rows = await listDecisions();
      setItems(rows);
      onCount(rows.length);
    } finally {
      setLoading(false);
    }
  }, [onCount]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const handleDelete = useCallback(async (id: number) => {
    if (!window.confirm("Delete this memory? This cannot be undone.")) return;
    try {
      await deleteDecision(id);
    } catch {
      window.alert("Failed to delete.");
      return;
    }
    void refresh();
  }, [refresh]);

  if (loading) return <div className="text-fg-muted text-sm">Loading…</div>;
  if (items.length === 0) return <EmptyState message={MEMORY_EMPTY} />;

  return (
    <div className="divide-y divide-line">
      {items.map((d) => (
        <DecisionRow
          key={d.id}
          decision={d}
          editing={editingId === d.id}
          onEdit={() => setEditingId(d.id)}
          onCancel={() => setEditingId(null)}
          onSave={async (patch) => {
            try {
              await updateDecision(d.id, patch);
            } catch {
              window.alert("Failed to save.");
              return;
            }
            setEditingId(null);
            void refresh();
          }}
          onDelete={() => handleDelete(d.id)}
        />
      ))}
    </div>
  );
}

function DecisionRow({
  decision,
  editing,
  onEdit,
  onCancel,
  onSave,
  onDelete,
}: {
  decision: Decision;
  editing: boolean;
  onEdit: () => void;
  onCancel: () => void;
  onSave: (patch: Partial<Decision>) => void;
  onDelete: () => void;
}) {
  const [domain, setDomain] = useState(decision.domain);
  const [summary, setSummary] = useState(decision.summary);
  const [rationale, setRationale] = useState(decision.rationale);
  const [outcome, setOutcome] = useState(decision.outcome);
  const [tags, setTags] = useState(decision.tags);

  useEffect(() => {
    if (editing) {
      setDomain(decision.domain);
      setSummary(decision.summary);
      setRationale(decision.rationale);
      setOutcome(decision.outcome);
      setTags(decision.tags);
    }
  }, [editing, decision]);

  return (
    <div className="group py-3 hover:bg-surface-overlay/30 transition-colors">
      <div className="flex items-start justify-between gap-3 mb-2">
        <div className="flex items-center gap-2 text-xs text-fg-muted">
          <span className="px-2 py-0.5 rounded bg-surface-overlay text-fg font-medium">{editing ? domain : decision.domain}</span>
          <span>{formatDate(decision.timestamp)}</span>
        </div>
        {!editing && (
          <div className="flex gap-2 opacity-0 group-hover:opacity-100 focus-within:opacity-100 transition-opacity">
            <button onClick={onEdit} className="text-xs text-fg-muted hover:text-fg">Edit</button>
            <button onClick={onDelete} className="text-xs text-red-400 hover:text-red-300">Delete</button>
          </div>
        )}
      </div>
      {editing ? (
        <div className="space-y-2">
          <select
            value={domain}
            onChange={(e) => setDomain(e.target.value)}
            className="w-full bg-surface border border-line rounded px-2 py-1.5 text-sm text-fg"
          >
            {DOMAINS.map((d) => <option key={d} value={d}>{d}</option>)}
          </select>
          <input
            type="text"
            value={summary}
            onChange={(e) => setSummary(e.target.value)}
            placeholder="Summary"
            className="w-full bg-surface border border-line rounded px-2 py-1.5 text-sm text-fg"
          />
          <textarea
            value={rationale}
            onChange={(e) => setRationale(e.target.value)}
            placeholder="Rationale"
            rows={2}
            className="w-full bg-surface border border-line rounded px-2 py-1.5 text-sm text-fg"
          />
          <input
            type="text"
            value={outcome}
            onChange={(e) => setOutcome(e.target.value)}
            placeholder="Outcome"
            className="w-full bg-surface border border-line rounded px-2 py-1.5 text-sm text-fg"
          />
          <input
            type="text"
            value={tags}
            onChange={(e) => setTags(e.target.value)}
            placeholder="Tags"
            className="w-full bg-surface border border-line rounded px-2 py-1.5 text-sm text-fg"
          />
          <div className="flex gap-2 justify-end">
            <button onClick={onCancel} className="text-xs px-3 py-1.5 rounded text-fg-muted hover:text-fg">Cancel</button>
            <button
              onClick={() => onSave({ domain, summary, rationale, outcome, tags })}
              className="text-xs px-3 py-1.5 rounded bg-indigo-600 hover:bg-indigo-500 text-white"
            >
              Save
            </button>
          </div>
        </div>
      ) : (
        <div className="space-y-1">
          <div className="text-sm text-fg line-clamp-2" title={decision.summary}>{decision.summary}</div>
          {decision.rationale && <div className="text-xs text-fg-muted line-clamp-2" title={`Rationale: ${decision.rationale}`}><span className="text-fg-muted">Rationale: </span>{decision.rationale}</div>}
          {decision.outcome && <div className="text-xs text-fg-muted line-clamp-2" title={`Outcome: ${decision.outcome}`}><span className="text-fg-muted">Outcome: </span>{decision.outcome}</div>}
          {decision.tags && <div className="text-xs text-fg-muted truncate" title={`Tags: ${decision.tags}`}>Tags: {decision.tags}</div>}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Initiatives
// ---------------------------------------------------------------------------

function InitiativesTab({ onCount }: { onCount: (n: number) => void }) {
  const [items, setItems] = useState<Initiative[]>([]);
  const [loading, setLoading] = useState(true);
  const [editingId, setEditingId] = useState<number | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const rows = await listInitiatives();
      setItems(rows);
      onCount(rows.length);
    } finally {
      setLoading(false);
    }
  }, [onCount]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const handleDelete = useCallback(async (id: number) => {
    if (!window.confirm("Delete this memory? This cannot be undone.")) return;
    try {
      await deleteInitiative(id);
    } catch {
      window.alert("Failed to delete.");
      return;
    }
    void refresh();
  }, [refresh]);

  if (loading) return <div className="text-fg-muted text-sm">Loading…</div>;
  if (items.length === 0) return <EmptyState message={MEMORY_EMPTY} />;

  return (
    <div className="divide-y divide-line">
      {items.map((it) => (
        <InitiativeRow
          key={it.id}
          initiative={it}
          editing={editingId === it.id}
          onEdit={() => setEditingId(it.id)}
          onCancel={() => setEditingId(null)}
          onSave={async (patch) => {
            try {
              await updateInitiative(it.id, patch);
            } catch {
              window.alert("Failed to save.");
              return;
            }
            setEditingId(null);
            void refresh();
          }}
          onDelete={() => handleDelete(it.id)}
        />
      ))}
    </div>
  );
}

function InitiativeRow({
  initiative,
  editing,
  onEdit,
  onCancel,
  onSave,
  onDelete,
}: {
  initiative: Initiative;
  editing: boolean;
  onEdit: () => void;
  onCancel: () => void;
  onSave: (patch: Partial<Initiative>) => void;
  onDelete: () => void;
}) {
  const [title, setTitle] = useState(initiative.title);
  const [status, setStatus] = useState(initiative.status);
  const [summary, setSummary] = useState(initiative.summary);

  useEffect(() => {
    if (editing) {
      setTitle(initiative.title);
      setStatus(initiative.status);
      setSummary(initiative.summary);
    }
  }, [editing, initiative]);

  return (
    <div className="group py-3 hover:bg-surface-overlay/30 transition-colors">
      <div className="flex items-start justify-between gap-3 mb-2">
        <div className="flex items-center gap-2 text-xs text-fg-muted">
          <span className="px-2 py-0.5 rounded bg-surface-overlay text-fg font-medium capitalize">{editing ? status : initiative.status}</span>
          <span>updated {formatDate(initiative.updated_at)}</span>
        </div>
        {!editing && (
          <div className="flex gap-2 opacity-0 group-hover:opacity-100 focus-within:opacity-100 transition-opacity">
            <button onClick={onEdit} className="text-xs text-fg-muted hover:text-fg">Edit</button>
            <button onClick={onDelete} className="text-xs text-red-400 hover:text-red-300">Delete</button>
          </div>
        )}
      </div>
      {editing ? (
        <div className="space-y-2">
          <input
            type="text"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Title"
            className="w-full bg-surface border border-line rounded px-2 py-1.5 text-sm text-fg"
          />
          <select
            value={status}
            onChange={(e) => setStatus(e.target.value)}
            className="w-full bg-surface border border-line rounded px-2 py-1.5 text-sm text-fg"
          >
            {STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
          <textarea
            value={summary}
            onChange={(e) => setSummary(e.target.value)}
            placeholder="Summary"
            rows={2}
            className="w-full bg-surface border border-line rounded px-2 py-1.5 text-sm text-fg"
          />
          <div className="flex gap-2 justify-end">
            <button onClick={onCancel} className="text-xs px-3 py-1.5 rounded text-fg-muted hover:text-fg">Cancel</button>
            <button
              onClick={() => onSave({ title, status, summary })}
              className="text-xs px-3 py-1.5 rounded bg-indigo-600 hover:bg-indigo-500 text-white"
            >
              Save
            </button>
          </div>
        </div>
      ) : (
        <div className="space-y-1">
          <div className="text-sm text-fg font-medium line-clamp-2" title={initiative.title}>{initiative.title}</div>
          {initiative.summary && <div className="text-xs text-fg-muted line-clamp-2" title={initiative.summary}>{initiative.summary}</div>}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Advice
// ---------------------------------------------------------------------------

function AdviceTab({ onCount }: { onCount: (n: number) => void }) {
  const [items, setItems] = useState<Advice[]>([]);
  const [loading, setLoading] = useState(true);
  const [editingId, setEditingId] = useState<number | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const rows = await listAdvice();
      setItems(rows);
      onCount(rows.length);
    } finally {
      setLoading(false);
    }
  }, [onCount]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const handleDelete = useCallback(async (id: number) => {
    if (!window.confirm("Delete this memory? This cannot be undone.")) return;
    try {
      await deleteAdvice(id);
    } catch {
      window.alert("Failed to delete.");
      return;
    }
    void refresh();
  }, [refresh]);

  if (loading) return <div className="text-fg-muted text-sm">Loading…</div>;
  if (items.length === 0) return <EmptyState message={MEMORY_EMPTY} />;

  return (
    <div className="divide-y divide-line">
      {items.map((a) => (
        <AdviceRow
          key={a.id}
          advice={a}
          editing={editingId === a.id}
          onEdit={() => setEditingId(a.id)}
          onCancel={() => setEditingId(null)}
          onSave={async (patch) => {
            try {
              await updateAdvice(a.id, patch);
            } catch {
              window.alert("Failed to save.");
              return;
            }
            setEditingId(null);
            void refresh();
          }}
          onDelete={() => handleDelete(a.id)}
        />
      ))}
    </div>
  );
}

function AdviceRow({
  advice,
  editing,
  onEdit,
  onCancel,
  onSave,
  onDelete,
}: {
  advice: Advice;
  editing: boolean;
  onEdit: () => void;
  onCancel: () => void;
  onSave: (patch: Partial<Advice>) => void;
  onDelete: () => void;
}) {
  const [domain, setDomain] = useState(advice.domain);
  const [querySummary, setQuerySummary] = useState(advice.query_summary);
  const [adviceSummary, setAdviceSummary] = useState(advice.advice_summary);

  useEffect(() => {
    if (editing) {
      setDomain(advice.domain);
      setQuerySummary(advice.query_summary);
      setAdviceSummary(advice.advice_summary);
    }
  }, [editing, advice]);

  return (
    <div className="group py-3 hover:bg-surface-overlay/30 transition-colors">
      <div className="flex items-start justify-between gap-3 mb-2">
        <div className="flex items-center gap-2 text-xs text-fg-muted">
          <span className="px-2 py-0.5 rounded bg-surface-overlay text-fg font-medium">{editing ? domain : advice.domain}</span>
          <span>{formatDate(advice.timestamp)}</span>
        </div>
        {!editing && (
          <div className="flex gap-2 opacity-0 group-hover:opacity-100 focus-within:opacity-100 transition-opacity">
            <button onClick={onEdit} className="text-xs text-fg-muted hover:text-fg">Edit</button>
            <button onClick={onDelete} className="text-xs text-red-400 hover:text-red-300">Delete</button>
          </div>
        )}
      </div>
      {editing ? (
        <div className="space-y-2">
          <select
            value={domain}
            onChange={(e) => setDomain(e.target.value)}
            className="w-full bg-surface border border-line rounded px-2 py-1.5 text-sm text-fg"
          >
            {DOMAINS.map((d) => <option key={d} value={d}>{d}</option>)}
          </select>
          <input
            type="text"
            value={querySummary}
            onChange={(e) => setQuerySummary(e.target.value)}
            placeholder="What the user asked"
            className="w-full bg-surface border border-line rounded px-2 py-1.5 text-sm text-fg"
          />
          <textarea
            value={adviceSummary}
            onChange={(e) => setAdviceSummary(e.target.value)}
            placeholder="Advice given"
            rows={3}
            className="w-full bg-surface border border-line rounded px-2 py-1.5 text-sm text-fg"
          />
          <div className="flex gap-2 justify-end">
            <button onClick={onCancel} className="text-xs px-3 py-1.5 rounded text-fg-muted hover:text-fg">Cancel</button>
            <button
              onClick={() => onSave({ domain, query_summary: querySummary, advice_summary: adviceSummary })}
              className="text-xs px-3 py-1.5 rounded bg-indigo-600 hover:bg-indigo-500 text-white"
            >
              Save
            </button>
          </div>
        </div>
      ) : (
        <div className="space-y-1">
          <div className="text-xs text-fg-muted line-clamp-2" title={`Q: ${advice.query_summary}`}>Q: {advice.query_summary}</div>
          <div className="text-sm text-fg line-clamp-2" title={advice.advice_summary}>{advice.advice_summary}</div>
        </div>
      )}
    </div>
  );
}
