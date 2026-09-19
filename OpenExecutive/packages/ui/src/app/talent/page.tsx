"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import {
  Candidate,
  Engagement,
  listCandidates,
  listEngagements,
} from "@/lib/api";
import { CandidateCard } from "@/components/talent/CandidateCard";
import { STAGE_META, PIPELINE_STAGES } from "@/components/talent/stages";

export default function TalentPage() {
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [engagements, setEngagements] = useState<Engagement[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [engagementFilter, setEngagementFilter] = useState<string>("");

  useEffect(() => {
    Promise.all([listCandidates(), listEngagements()])
      .then(([c, e]) => {
        setCandidates(c);
        setEngagements(e);
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load"))
      .finally(() => setLoading(false));
  }, []);

  const filtered = useMemo(() => {
    if (!engagementFilter) return candidates;
    const id = Number(engagementFilter);
    return candidates.filter((c) => c.engagement_id === id);
  }, [candidates, engagementFilter]);

  const byStage = useMemo(() => {
    const map: Record<string, Candidate[]> = {};
    for (const c of filtered) (map[c.stage] ??= []).push(c);
    return map;
  }, [filtered]);

  const rejected = byStage["rejected"] ?? [];

  return (
    <div className="flex flex-col h-full bg-surface">
      <main className="flex-1 overflow-y-auto">
        <div className="max-w-7xl mx-auto px-6 py-6">
          <div className="flex items-baseline justify-between mb-6 gap-4 flex-wrap">
            <div>
              <h1 className="text-xl font-semibold text-fg">Talent Pipeline</h1>
              <p className="text-sm text-fg-muted mt-0.5">
                Candidates across all searches, by stage. Manage open roles under{" "}
                <Link href="/talent/searches" className="text-indigo-300 hover:text-indigo-200">
                  Searches
                </Link>
                .
              </p>
            </div>
            <div className="flex items-center gap-2">
              <select
                value={engagementFilter}
                onChange={(e) => setEngagementFilter(e.target.value)}
                className="px-3 py-2 rounded-lg bg-surface-input border border-line text-sm focus:outline-none focus:border-indigo-500"
              >
                <option value="">All engagements</option>
                {engagements.map((e) => (
                  <option key={e.id} value={String(e.id)}>
                    {e.role_title}
                  </option>
                ))}
              </select>
              <Link
                href="/talent/searches"
                className="px-4 py-2 text-sm rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white font-medium"
              >
                Searches →
              </Link>
            </div>
          </div>

          {loading && <p className="text-fg-muted text-sm">Loading…</p>}
          {error && (
            <div className="p-3 rounded-lg bg-rose-500/10 border border-rose-500/30 text-rose-300 text-sm mb-4">
              {error}
            </div>
          )}
          {!loading && !error && candidates.length === 0 && (
            <div className="rounded-xl border border-line bg-surface-elevated p-8 text-center">
              <p className="text-fg-muted text-sm mb-3">No candidates yet.</p>
              <Link
                href="/talent/searches"
                className="px-4 py-2 text-sm rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white"
              >
                Open a search →
              </Link>
            </div>
          )}

          {!loading && !error && candidates.length > 0 && (
            <>
              <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-3">
                {PIPELINE_STAGES.map((stage) => {
                  const items = byStage[stage] ?? [];
                  return (
                    <div key={stage} className="flex flex-col">
                      <div className="flex items-center justify-between mb-2 px-1">
                        <span className="text-xs font-semibold text-fg-muted uppercase tracking-wide">
                          {STAGE_META[stage].label}
                        </span>
                        <span className="text-xs text-fg-subtle tabular-nums">{items.length}</span>
                      </div>
                      <div className="space-y-2">
                        {items.map((c) => (
                          <CandidateCard key={c.id} candidate={c} />
                        ))}
                        {items.length === 0 && (
                          <div className="rounded-xl border border-dashed border-line p-4 text-center text-[11px] text-fg-subtle">
                            None
                          </div>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>

              {rejected.length > 0 && (
                <div className="mt-8">
                  <div className="text-xs font-semibold text-fg-muted uppercase tracking-wide mb-2">
                    Rejected ({rejected.length})
                  </div>
                  <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-3">
                    {rejected.map((c) => (
                      <CandidateCard key={c.id} candidate={c} />
                    ))}
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      </main>
    </div>
  );
}
