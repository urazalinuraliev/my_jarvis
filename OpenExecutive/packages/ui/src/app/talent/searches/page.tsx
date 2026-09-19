"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import {
  Engagement,
  EngagementStatus,
  createEngagement,
  listEngagements,
  reindexTalent,
} from "@/lib/api";
import { StatusBadge } from "@/components/talent/StageBadge";

function AddSearchModal({
  onCreated,
  onClose,
}: {
  onCreated: (e: Engagement) => void;
  onClose: () => void;
}) {
  const [form, setForm] = useState({
    role_title: "",
    department: "",
    location: "",
    comp_band: "",
    must_haves: "",
    description: "",
  });
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function submit() {
    setSaving(true);
    setErr(null);
    try {
      const e = await createEngagement({
        role_title: form.role_title.trim(),
        department: form.department.trim(),
        location: form.location.trim(),
        comp_band: form.comp_band.trim(),
        must_haves: form.must_haves.trim(),
        description: form.description.trim(),
      });
      onCreated(e);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Failed to create");
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" onClick={onClose}>
      <div
        className="w-full max-w-lg bg-surface border border-line rounded-2xl shadow-2xl p-6 mx-4 max-h-[90vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="text-lg font-semibold text-fg mb-4">New search</h2>
        <div className="space-y-3">
          <label className="block">
            <span className="text-xs text-fg-muted">Role title *</span>
            <input
              value={form.role_title}
              onChange={(e) => setForm((f) => ({ ...f, role_title: e.target.value }))}
              className="mt-1 w-full px-3 py-2 rounded-lg bg-surface-input border border-line text-sm focus:outline-none focus:border-indigo-500"
              placeholder="VP Drilling"
            />
          </label>
          <div className="grid grid-cols-2 gap-3">
            <label className="block">
              <span className="text-xs text-fg-muted">Department</span>
              <input
                value={form.department}
                onChange={(e) => setForm((f) => ({ ...f, department: e.target.value }))}
                className="mt-1 w-full px-3 py-2 rounded-lg bg-surface-input border border-line text-sm focus:outline-none focus:border-indigo-500"
                placeholder="Drilling"
              />
            </label>
            <label className="block">
              <span className="text-xs text-fg-muted">Location</span>
              <input
                value={form.location}
                onChange={(e) => setForm((f) => ({ ...f, location: e.target.value }))}
                className="mt-1 w-full px-3 py-2 rounded-lg bg-surface-input border border-line text-sm focus:outline-none focus:border-indigo-500"
                placeholder="Midland, TX"
              />
            </label>
          </div>
          <label className="block">
            <span className="text-xs text-fg-muted">Comp band</span>
            <input
              value={form.comp_band}
              onChange={(e) => setForm((f) => ({ ...f, comp_band: e.target.value }))}
              className="mt-1 w-full px-3 py-2 rounded-lg bg-surface-input border border-line text-sm focus:outline-none focus:border-indigo-500"
              placeholder="$300-350K + equity"
            />
          </label>
          <label className="block">
            <span className="text-xs text-fg-muted">Must-haves</span>
            <textarea
              value={form.must_haves}
              onChange={(e) => setForm((f) => ({ ...f, must_haves: e.target.value }))}
              rows={3}
              className="mt-1 w-full px-3 py-2 rounded-lg bg-surface-input border border-line text-sm focus:outline-none focus:border-indigo-500"
              placeholder="10+ yrs upstream, cycle-tested, HSE track record"
            />
          </label>
          <label className="block">
            <span className="text-xs text-fg-muted">Description</span>
            <textarea
              value={form.description}
              onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
              rows={3}
              className="mt-1 w-full px-3 py-2 rounded-lg bg-surface-input border border-line text-sm focus:outline-none focus:border-indigo-500"
            />
          </label>
        </div>
        {err && <p className="text-xs text-rose-300 mt-3">{err}</p>}
        <div className="flex gap-2 mt-5">
          <button
            disabled={saving || !form.role_title.trim()}
            onClick={submit}
            className="flex-1 py-2 text-sm rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white disabled:opacity-50 font-medium"
          >
            {saving ? "Creating…" : "Create search"}
          </button>
          <button
            disabled={saving}
            onClick={onClose}
            className="px-4 py-2 text-sm rounded-lg border border-line hover:bg-surface-overlay disabled:opacity-50"
          >
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}

export default function SearchesPage() {
  const [engagements, setEngagements] = useState<Engagement[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showAdd, setShowAdd] = useState(false);
  const [reindexMsg, setReindexMsg] = useState<string | null>(null);

  useEffect(() => {
    listEngagements()
      .then(setEngagements)
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load"))
      .finally(() => setLoading(false));
  }, []);

  // Repair action: rebuild the candidate match index from the database. Normal
  // create/edit/stage/archive already auto-index — this is only for when the
  // vector index drifts out of sync (e.g. it was wiped or an index write failed).
  async function handleReindex() {
    setReindexMsg("Reindexing…");
    try {
      const { indexed } = await reindexTalent();
      setReindexMsg(`Reindexed ${indexed} candidate(s).`);
    } catch (e) {
      setReindexMsg(e instanceof Error ? e.message : "Reindex failed");
    }
  }

  return (
    <div className="flex flex-col h-full bg-surface">
      {showAdd && (
        <AddSearchModal
          onCreated={(e) => {
            setEngagements((prev) => [...prev, e]);
            setShowAdd(false);
          }}
          onClose={() => setShowAdd(false)}
        />
      )}
      <main className="flex-1 overflow-y-auto">
        <div className="max-w-4xl mx-auto px-6 py-6">
          <Link href="/talent" className="text-xs text-fg-muted hover:text-fg">
            ← Talent pipeline
          </Link>

          <div className="flex items-baseline justify-between mt-2 mb-6 gap-4">
            <div>
              <h1 className="text-xl font-semibold text-fg">Searches</h1>
              <p className="text-sm text-fg-muted mt-0.5">
                Open roles we&apos;re hiring for in this company.
              </p>
            </div>
            <div className="flex items-center gap-2">
              <button
                onClick={handleReindex}
                className="px-3 py-2 text-sm rounded-lg border border-line hover:bg-surface-overlay text-fg"
                title="Rebuild the talent-match index from the database (repair tool)"
              >
                Reindex
              </button>
              <button
                onClick={() => setShowAdd(true)}
                className="px-4 py-2 text-sm rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white font-medium"
              >
                + New search
              </button>
            </div>
          </div>

          {reindexMsg && <div className="mb-4 text-xs text-fg-muted">{reindexMsg}</div>}
          {loading && <p className="text-fg-muted text-sm">Loading…</p>}
          {error && (
            <div className="p-3 rounded-lg bg-rose-500/10 border border-rose-500/30 text-rose-300 text-sm mb-4">
              {error}
            </div>
          )}
          {!loading && !error && engagements.length === 0 && (
            <div className="rounded-xl border border-line bg-surface-elevated p-8 text-center">
              <p className="text-fg-muted text-sm mb-3">No searches yet.</p>
              <button
                onClick={() => setShowAdd(true)}
                className="px-4 py-2 text-sm rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white"
              >
                Open your first search →
              </button>
            </div>
          )}
          {!loading && !error && engagements.length > 0 && (
            <div className="space-y-2">
              {engagements.map((e) => (
                <Link
                  key={e.id}
                  href={`/talent/engagements/${e.id}`}
                  className="flex items-center justify-between rounded-xl border border-line bg-surface-elevated hover:bg-surface-overlay transition-colors p-3 group"
                >
                  <div>
                    <div className="text-sm font-semibold text-fg group-hover:text-indigo-300">
                      {e.role_title}
                    </div>
                    <div className="text-xs text-fg-muted mt-0.5">
                      {[e.department, e.location, e.comp_band].filter(Boolean).join(" · ") || "—"}
                    </div>
                  </div>
                  <StatusBadge status={e.status as EngagementStatus} />
                </Link>
              ))}
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
