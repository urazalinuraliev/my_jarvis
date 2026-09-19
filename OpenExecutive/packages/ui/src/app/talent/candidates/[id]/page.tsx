"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";

import {
  Candidate,
  CandidateMatch,
  CandidateStage,
  CANDIDATE_STAGES,
  archiveCandidate,
  getCandidate,
  listCandidates,
  setCandidateStage,
  similarCandidates,
  updateCandidate,
} from "@/lib/api";
import { OfferPanel } from "@/components/talent/OfferPanel";
import { StageBadge } from "@/components/talent/StageBadge";
import { STAGE_META, fitScoreColor } from "@/components/talent/stages";
import { workflowLink } from "@/components/talent/workflowLink";

const EDIT_FIELDS: [keyof Candidate, string][] = [
  ["full_name", "Full name"],
  ["current_title", "Current title"],
  ["current_company", "Current company"],
  ["location", "Location"],
  ["email", "Email"],
  ["linkedin_url", "LinkedIn URL"],
  ["source", "Source"],
  ["notes", "Notes"],
];

export default function CandidateDetailPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const candidateId = params?.id ? Number(params.id) : null;

  const [candidate, setCandidate] = useState<Candidate | null>(null);
  const [similar, setSimilar] = useState<CandidateMatch[]>([]);
  const [nameById, setNameById] = useState<Map<number, Candidate>>(new Map());
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState(false);
  const [editForm, setEditForm] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [stageBusy, setStageBusy] = useState(false);

  const load = useCallback(() => {
    if (candidateId == null) return;
    getCandidate(candidateId)
      .then((c) => {
        setCandidate(c);
        setEditForm({
          full_name: c.full_name,
          current_title: c.current_title,
          current_company: c.current_company,
          location: c.location,
          email: c.email ?? "",
          linkedin_url: c.linkedin_url ?? "",
          source: c.source,
          notes: c.notes,
        });
      })
      .catch((e) => setError(e instanceof Error ? e.message : "Failed to load"))
      .finally(() => setLoading(false));
    similarCandidates(candidateId).then(setSimilar).catch(() => setSimilar([]));
    listCandidates()
      .then((all) => setNameById(new Map(all.map((c) => [c.id, c]))))
      .catch(() => setNameById(new Map()));
  }, [candidateId]);

  useEffect(() => {
    load();
  }, [load]);

  const workflowActions = useMemo(() => {
    if (!candidate) return [];
    const cid = String(candidate.id);
    const eid = String(candidate.engagement_id);
    return [
      { label: "Screen", href: workflowLink("candidate_screen", { engagement_id: eid, candidate_id: cid }) },
      { label: "Outreach", href: workflowLink("candidate_outreach", { candidate_id: cid }) },
      { label: "Interviews", href: workflowLink("interview_coordination", { candidate_id: cid }) },
      { label: "References", href: workflowLink("reference_check", { candidate_id: cid }) },
      { label: "Offer", href: workflowLink("offer_approval", { candidate_id: cid }) },
      { label: "Onboarding", href: workflowLink("new_hire_onboarding", { candidate_id: cid }) },
    ];
  }, [candidate]);

  async function saveEdits() {
    if (candidateId == null) return;
    setSaving(true);
    try {
      const updated = await updateCandidate(candidateId, {
        full_name: editForm.full_name,
        current_title: editForm.current_title,
        current_company: editForm.current_company,
        location: editForm.location,
        email: editForm.email || null,
        linkedin_url: editForm.linkedin_url || null,
        source: editForm.source,
        notes: editForm.notes,
      });
      setCandidate(updated);
      setEditing(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save");
    } finally {
      setSaving(false);
    }
  }

  async function moveStage(stage: CandidateStage) {
    if (candidateId == null || !candidate || candidate.stage === stage) return;
    setStageBusy(true);
    try {
      setCandidate(await setCandidateStage(candidateId, stage));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to move stage");
    } finally {
      setStageBusy(false);
    }
  }

  async function handleArchive() {
    if (candidateId == null || !candidate) return;
    try {
      await archiveCandidate(candidateId);
      router.push(`/talent/engagements/${candidate.engagement_id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to archive");
    }
  }

  if (loading) return <div className="p-6 text-fg-muted text-sm">Loading…</div>;
  if (error && !candidate) {
    return (
      <div className="p-6">
        <div className="p-3 rounded-lg bg-rose-500/10 border border-rose-500/30 text-rose-300 text-sm">
          {error}
        </div>
      </div>
    );
  }
  if (!candidate) return <div className="p-6 text-fg-muted text-sm">Candidate not found.</div>;

  const subtitle = [candidate.current_title, candidate.current_company].filter(Boolean).join(" · ");

  return (
    <div className="flex flex-col h-full bg-surface">
      <main className="flex-1 overflow-y-auto">
        <div className="max-w-4xl mx-auto px-6 py-6">
          <Link
            href={`/talent/engagements/${candidate.engagement_id}`}
            className="text-xs text-fg-muted hover:text-fg"
          >
            ← Engagement
          </Link>

          <div className="flex items-start justify-between mt-2 mb-6 gap-4">
            <div className="min-w-0">
              <h1 className="text-xl font-semibold text-fg flex items-center gap-2">
                {candidate.full_name}
                <StageBadge stage={candidate.stage} />
              </h1>
              {subtitle && <p className="text-sm text-fg-muted mt-0.5">{subtitle}</p>}
            </div>
            <div className="flex items-center gap-3 shrink-0">
              <div className="text-right">
                <div className={`text-2xl font-bold tabular-nums ${fitScoreColor(candidate.fit_score)}`}>
                  {candidate.fit_score ?? "—"}
                </div>
                <div className="text-[10px] text-fg-subtle uppercase">Fit score</div>
              </div>
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

          {error && (
            <div className="p-3 rounded-lg bg-rose-500/10 border border-rose-500/30 text-rose-300 text-sm mb-4">
              {error}
            </div>
          )}

          {/* Stage control */}
          <div className="mb-6">
            <div className="text-xs font-semibold text-fg-muted uppercase tracking-wide mb-2">
              Pipeline stage
            </div>
            <div className="flex flex-wrap gap-2">
              {CANDIDATE_STAGES.map((stage) => {
                const active = candidate.stage === stage;
                return (
                  <button
                    key={stage}
                    disabled={stageBusy || active}
                    onClick={() => moveStage(stage)}
                    className={`px-3 py-1.5 rounded-lg border text-xs font-medium transition-colors disabled:opacity-100 ${
                      active
                        ? "bg-indigo-600/30 border-indigo-500/50 text-indigo-200"
                        : "bg-surface-input border-line text-fg-muted hover:border-indigo-500/40 disabled:opacity-50"
                    }`}
                  >
                    {STAGE_META[stage].label}
                  </button>
                );
              })}
            </div>
          </div>

          {/* Offer lifecycle */}
          <OfferPanel candidate={candidate} onChanged={load} />

          {/* Run workflows */}
          <div className="mb-6">
            <div className="text-xs font-semibold text-fg-muted uppercase tracking-wide mb-2">
              Run a workflow
            </div>
            <div className="flex flex-wrap gap-2">
              {workflowActions.map((a) => (
                <Link
                  key={a.label}
                  href={a.href}
                  className="px-3 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-medium"
                >
                  {a.label}
                </Link>
              ))}
            </div>
          </div>

          {editing && (
            <div className="rounded-xl border border-line bg-surface-elevated p-4 mb-6 space-y-3">
              {EDIT_FIELDS.map(([key, label]) => (
                <label key={key} className="block">
                  <span className="text-xs text-fg-muted">{label}</span>
                  {key === "notes" ? (
                    <textarea
                      value={editForm[key] ?? ""}
                      onChange={(e) => setEditForm((f) => ({ ...f, [key]: e.target.value }))}
                      rows={3}
                      className="mt-1 w-full px-3 py-2 rounded-lg bg-surface-input border border-line text-sm focus:outline-none focus:border-indigo-500"
                    />
                  ) : (
                    <input
                      value={editForm[key] ?? ""}
                      onChange={(e) => setEditForm((f) => ({ ...f, [key]: e.target.value }))}
                      className="mt-1 w-full px-3 py-2 rounded-lg bg-surface-input border border-line text-sm focus:outline-none focus:border-indigo-500"
                    />
                  )}
                </label>
              ))}
              <button
                disabled={saving || !editForm.full_name?.trim()}
                onClick={saveEdits}
                className="px-4 py-2 text-sm rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white disabled:opacity-50 font-medium"
              >
                {saving ? "Saving…" : "Save"}
              </button>
            </div>
          )}

          {/* Screening summary */}
          {candidate.screening_summary && (
            <div className="mb-6">
              <div className="text-xs font-semibold text-fg-muted uppercase tracking-wide mb-1">
                Screening summary
              </div>
              <p className="text-sm text-fg-muted whitespace-pre-wrap">{candidate.screening_summary}</p>
            </div>
          )}

          {candidate.notes && !editing && (
            <div className="mb-6">
              <div className="text-xs font-semibold text-fg-muted uppercase tracking-wide mb-1">Notes</div>
              <p className="text-sm text-fg-muted whitespace-pre-wrap">{candidate.notes}</p>
            </div>
          )}

          {/* Similar candidates */}
          <div className="border-t border-line pt-6">
            <div className="text-xs font-semibold text-fg-muted uppercase tracking-wide mb-2">
              Similar candidates
            </div>
            {similar.length === 0 ? (
              <p className="text-sm text-fg-subtle">No similar candidates indexed yet.</p>
            ) : (
              <div className="space-y-2">
                {similar.map((m) => {
                  const cand = nameById.get(m.candidate_id);
                  return (
                    <Link
                      key={m.candidate_id}
                      href={`/talent/candidates/${m.candidate_id}`}
                      className="flex items-center justify-between rounded-xl border border-line bg-surface-elevated hover:bg-surface-overlay transition-colors p-3 group"
                    >
                      <span className="text-sm text-fg group-hover:text-indigo-300 truncate">
                        {cand ? cand.full_name : `Candidate #${m.candidate_id}`}
                      </span>
                      <span className={`text-sm font-semibold tabular-nums ${fitScoreColor(Math.round(m.score * 100))}`}>
                        {Math.round(m.score * 100)}%
                      </span>
                    </Link>
                  );
                })}
              </div>
            )}
          </div>
        </div>
      </main>
    </div>
  );
}
