"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";

import {
  Candidate,
  CandidateMatch,
  Engagement,
  ENGAGEMENT_STATUSES,
  EngagementStatus,
  archiveEngagement,
  createCandidate,
  getEngagement,
  listCandidates,
  matchCandidatesForEngagement,
  updateEngagement,
} from "@/lib/api";
import { CandidateCard } from "@/components/talent/CandidateCard";
import { StatusBadge } from "@/components/talent/StageBadge";
import { fitScoreColor } from "@/components/talent/stages";

function AddCandidateModal({
  engagementId,
  onCreated,
  onClose,
}: {
  engagementId: number;
  onCreated: (c: Candidate) => void;
  onClose: () => void;
}) {
  const [form, setForm] = useState({
    full_name: "",
    current_title: "",
    current_company: "",
    location: "",
    email: "",
    linkedin_url: "",
    source: "",
  });
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function submit() {
    setSaving(true);
    setErr(null);
    try {
      const c = await createCandidate({
        engagement_id: engagementId,
        full_name: form.full_name.trim(),
        current_title: form.current_title.trim(),
        current_company: form.current_company.trim(),
        location: form.location.trim(),
        email: form.email.trim() || null,
        linkedin_url: form.linkedin_url.trim() || null,
        source: form.source.trim(),
      });
      onCreated(c);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Failed to create");
      setSaving(false);
    }
  }

  const fields: [keyof typeof form, string, string][] = [
    ["full_name", "Full name *", "Dana Cole"],
    ["current_title", "Current title", "Drilling Director"],
    ["current_company", "Current company", "Permian Co"],
    ["location", "Location", "Midland, TX"],
    ["email", "Email", "dana@example.com"],
    ["linkedin_url", "LinkedIn URL", "https://linkedin.com/in/…"],
    ["source", "Source", "referral"],
  ];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" onClick={onClose}>
      <div
        className="w-full max-w-lg bg-surface border border-line rounded-2xl shadow-2xl p-6 mx-4 max-h-[90vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="text-lg font-semibold text-fg mb-4">Add candidate</h2>
        <div className="space-y-3">
          {fields.map(([key, label, placeholder]) => (
            <label key={key} className="block">
              <span className="text-xs text-fg-muted">{label}</span>
              <input
                value={form[key]}
                onChange={(e) => setForm((f) => ({ ...f, [key]: e.target.value }))}
                className="mt-1 w-full px-3 py-2 rounded-lg bg-surface-input border border-line text-sm focus:outline-none focus:border-indigo-500"
                placeholder={placeholder}
              />
            </label>
          ))}
        </div>
        {err && <p className="text-xs text-rose-300 mt-3">{err}</p>}
        <div className="flex gap-2 mt-5">
          <button
            disabled={saving || !form.full_name.trim()}
            onClick={submit}
            className="flex-1 py-2 text-sm rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white disabled:opacity-50 font-medium"
          >
            {saving ? "Adding…" : "Add candidate"}
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

export default function EngagementDetailPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const engagementId = params?.id ? Number(params.id) : null;

  const [engagement, setEngagement] = useState<Engagement | null>(null);
  const [allCandidates, setAllCandidates] = useState<Candidate[]>([]);
  const [matches, setMatches] = useState<CandidateMatch[] | null>(null);
  const [matchError, setMatchError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState(false);
  const [editForm, setEditForm] = useState<{
    role_title: string;
    department: string;
    status: EngagementStatus;
    location: string;
    comp_band: string;
    must_haves: string;
    description: string;
  }>({ role_title: "", department: "", status: "open", location: "", comp_band: "", must_haves: "", description: "" });
  const [saving, setSaving] = useState(false);
  const [showAddCandidate, setShowAddCandidate] = useState(false);

  const load = useCallback(() => {
    if (engagementId == null) return;
    getEngagement(engagementId)
      .then(async (e) => {
        setEngagement(e);
        setEditForm({
          role_title: e.role_title,
          department: e.department,
          status: e.status,
          location: e.location,
          comp_band: e.comp_band,
          must_haves: e.must_haves,
          description: e.description,
        });
        setAllCandidates(await listCandidates());
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load"))
      .finally(() => setLoading(false));
  }, [engagementId]);

  useEffect(() => {
    load();
  }, [load]);

  const engagementCandidates = useMemo(
    () => allCandidates.filter((c) => c.engagement_id === engagementId),
    [allCandidates, engagementId],
  );
  const nameById = useMemo(() => {
    const m = new Map<number, Candidate>();
    for (const c of allCandidates) m.set(c.id, c);
    return m;
  }, [allCandidates]);

  async function saveEdits() {
    if (engagementId == null) return;
    setSaving(true);
    try {
      const updated = await updateEngagement(engagementId, editForm);
      setEngagement(updated);
      setEditing(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save");
    } finally {
      setSaving(false);
    }
  }

  async function handleArchive() {
    if (engagementId == null || !engagement) return;
    try {
      await archiveEngagement(engagementId);
      router.push("/talent/searches");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to archive");
    }
  }

  async function loadMatches() {
    if (engagementId == null) return;
    setMatchError(null);
    try {
      setMatches(await matchCandidatesForEngagement(engagementId));
    } catch (e) {
      setMatchError(e instanceof Error ? e.message : "Failed to load matches");
    }
  }

  if (loading) return <div className="p-6 text-fg-muted text-sm">Loading…</div>;
  if (error) {
    return (
      <div className="p-6">
        <div className="p-3 rounded-lg bg-rose-500/10 border border-rose-500/30 text-rose-300 text-sm">
          {error}
        </div>
      </div>
    );
  }
  if (!engagement) return <div className="p-6 text-fg-muted text-sm">Engagement not found.</div>;

  return (
    <div className="flex flex-col h-full bg-surface">
      {showAddCandidate && engagementId != null && (
        <AddCandidateModal
          engagementId={engagementId}
          onCreated={(c) => {
            setAllCandidates((prev) => [...prev, c]);
            setShowAddCandidate(false);
          }}
          onClose={() => setShowAddCandidate(false)}
        />
      )}
      <main className="flex-1 overflow-y-auto">
        <div className="max-w-4xl mx-auto px-6 py-6">
          <Link
            href="/talent/searches"
            className="text-xs text-fg-muted hover:text-fg"
          >
            ← Searches
          </Link>

          <div className="flex items-start justify-between mt-2 mb-6 gap-4">
            <div className="min-w-0">
              <h1 className="text-xl font-semibold text-fg flex items-center gap-2">
                {engagement.role_title}
                <StatusBadge status={engagement.status} />
              </h1>
              <p className="text-sm text-fg-muted mt-0.5">
                {[engagement.department, engagement.location, engagement.comp_band]
                  .filter(Boolean)
                  .join(" · ") || "—"}
              </p>
            </div>
            <div className="flex gap-2 shrink-0">
              <button
                onClick={() => setEditing((v) => !v)}
                className="px-3 py-2 text-sm rounded-lg border border-line hover:bg-surface-overlay text-fg"
              >
                {editing ? "Cancel" : "Edit"}
              </button>
              <button
                onClick={handleArchive}
                className="px-3 py-2 text-sm rounded-lg border border-rose-500/40 text-rose-300 hover:bg-rose-500/10"
              >
                Archive
              </button>
            </div>
          </div>

          {editing && (
            <div className="rounded-xl border border-line bg-surface-elevated p-4 mb-6 space-y-3">
              <div className="grid grid-cols-2 gap-3">
                <label className="block">
                  <span className="text-xs text-fg-muted">Role title</span>
                  <input
                    value={editForm.role_title}
                    onChange={(e) => setEditForm((f) => ({ ...f, role_title: e.target.value }))}
                    className="mt-1 w-full px-3 py-2 rounded-lg bg-surface-input border border-line text-sm focus:outline-none focus:border-indigo-500"
                  />
                </label>
                <label className="block">
                  <span className="text-xs text-fg-muted">Department</span>
                  <input
                    value={editForm.department}
                    onChange={(e) => setEditForm((f) => ({ ...f, department: e.target.value }))}
                    className="mt-1 w-full px-3 py-2 rounded-lg bg-surface-input border border-line text-sm focus:outline-none focus:border-indigo-500"
                  />
                </label>
              </div>
              <div className="grid grid-cols-3 gap-3">
                <label className="block">
                  <span className="text-xs text-fg-muted">Status</span>
                  <select
                    value={editForm.status}
                    onChange={(e) =>
                      setEditForm((f) => ({ ...f, status: e.target.value as EngagementStatus }))
                    }
                    className="mt-1 w-full px-3 py-2 rounded-lg bg-surface-input border border-line text-sm focus:outline-none focus:border-indigo-500"
                  >
                    {ENGAGEMENT_STATUSES.map((s) => (
                      <option key={s} value={s}>
                        {s}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="block">
                  <span className="text-xs text-fg-muted">Location</span>
                  <input
                    value={editForm.location}
                    onChange={(e) => setEditForm((f) => ({ ...f, location: e.target.value }))}
                    className="mt-1 w-full px-3 py-2 rounded-lg bg-surface-input border border-line text-sm focus:outline-none focus:border-indigo-500"
                  />
                </label>
                <label className="block">
                  <span className="text-xs text-fg-muted">Comp band</span>
                  <input
                    value={editForm.comp_band}
                    onChange={(e) => setEditForm((f) => ({ ...f, comp_band: e.target.value }))}
                    className="mt-1 w-full px-3 py-2 rounded-lg bg-surface-input border border-line text-sm focus:outline-none focus:border-indigo-500"
                  />
                </label>
              </div>
              <label className="block">
                <span className="text-xs text-fg-muted">Must-haves</span>
                <textarea
                  value={editForm.must_haves}
                  onChange={(e) => setEditForm((f) => ({ ...f, must_haves: e.target.value }))}
                  rows={3}
                  className="mt-1 w-full px-3 py-2 rounded-lg bg-surface-input border border-line text-sm focus:outline-none focus:border-indigo-500"
                />
              </label>
              <label className="block">
                <span className="text-xs text-fg-muted">Description</span>
                <textarea
                  value={editForm.description}
                  onChange={(e) => setEditForm((f) => ({ ...f, description: e.target.value }))}
                  rows={3}
                  className="mt-1 w-full px-3 py-2 rounded-lg bg-surface-input border border-line text-sm focus:outline-none focus:border-indigo-500"
                />
              </label>
              <button
                disabled={saving}
                onClick={saveEdits}
                className="px-4 py-2 text-sm rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white disabled:opacity-50 font-medium"
              >
                {saving ? "Saving…" : "Save"}
              </button>
            </div>
          )}

          {engagement.must_haves && !editing && (
            <div className="mb-6">
              <div className="text-xs font-semibold text-fg-muted uppercase tracking-wide mb-1">
                Must-haves
              </div>
              <p className="text-sm text-fg-muted whitespace-pre-wrap">{engagement.must_haves}</p>
            </div>
          )}

          {/* Candidates */}
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-semibold text-fg">
              Candidates ({engagementCandidates.length})
            </h2>
            <button
              onClick={() => setShowAddCandidate(true)}
              className="px-3 py-1.5 text-xs rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white font-medium"
            >
              + Add candidate
            </button>
          </div>
          {engagementCandidates.length === 0 ? (
            <p className="text-sm text-fg-subtle mb-6">No candidates yet.</p>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3 mb-6">
              {engagementCandidates.map((c) => (
                <CandidateCard key={c.id} candidate={c} />
              ))}
            </div>
          )}

          {/* Talent-graph matches */}
          <div className="flex items-center justify-between mb-3 border-t border-line pt-6">
            <div>
              <h2 className="text-sm font-semibold text-fg">Suggested matches</h2>
              <p className="text-xs text-fg-muted mt-0.5">
                Best-fit candidates across the whole pool, ranked against this role.
              </p>
            </div>
            <button
              onClick={loadMatches}
              className="px-3 py-1.5 text-xs rounded-lg border border-line hover:bg-surface-overlay text-fg"
            >
              {matches ? "Refresh" : "Find matches"}
            </button>
          </div>
          {matchError && <p className="text-sm text-rose-300">{matchError}</p>}
          {matches && matches.length === 0 && (
            <p className="text-sm text-fg-subtle">No matches found (try Reindex on the pipeline).</p>
          )}
          {matches && matches.length > 0 && (
            <div className="space-y-2">
              {matches.map((m) => {
                const cand = nameById.get(m.candidate_id);
                return (
                  <Link
                    key={m.candidate_id}
                    href={`/talent/candidates/${m.candidate_id}`}
                    className="flex items-center justify-between rounded-xl border border-line bg-surface-elevated hover:bg-surface-overlay transition-colors p-3 group"
                  >
                    <div className="min-w-0">
                      <div className="text-sm font-semibold text-fg group-hover:text-indigo-300 truncate">
                        {cand ? cand.full_name : `Candidate #${m.candidate_id}`}
                      </div>
                      <div className="text-xs text-fg-muted truncate">
                        {cand?.current_title || m.stage}
                      </div>
                    </div>
                    <div
                      className={`text-sm font-semibold tabular-nums ${fitScoreColor(
                        Math.round(m.score * 100),
                      )}`}
                      title="Match score"
                    >
                      {Math.round(m.score * 100)}%
                    </div>
                  </Link>
                );
              })}
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
