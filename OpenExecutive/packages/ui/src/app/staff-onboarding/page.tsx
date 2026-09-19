"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import {
  OnboardingPlan,
  OnboardingTemplate,
  createOnboardingPlan,
  listOnboardingPlans,
  listOnboardingTemplates,
} from "@/lib/api";
import { PHASE_LABEL, STATUS_META, STATUS_ORDER } from "@/components/onboarding/meta";

function ProgressBar({ pct }: { pct: number }) {
  return (
    <div className="h-1.5 w-full rounded-full bg-surface-input overflow-hidden">
      <div
        className="h-full rounded-full bg-emerald-500/70"
        style={{ width: `${Math.max(0, Math.min(100, pct))}%` }}
      />
    </div>
  );
}

export default function StaffOnboardingPage() {
  const [plans, setPlans] = useState<OnboardingPlan[]>([]);
  const [templates, setTemplates] = useState<OnboardingTemplate[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [saving, setSaving] = useState(false);

  const [fullName, setFullName] = useState("");
  const [startDate, setStartDate] = useState("");
  const [role, setRole] = useState("");
  const [templateName, setTemplateName] = useState("");

  function load() {
    setLoading(true);
    Promise.all([listOnboardingPlans(), listOnboardingTemplates()])
      .then(([p, t]) => {
        setPlans(p);
        setTemplates(t);
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load"))
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    load();
  }, []);

  const sorted = useMemo(
    () =>
      [...plans].sort(
        (a, b) =>
          (STATUS_ORDER[a.status] ?? 9) - (STATUS_ORDER[b.status] ?? 9) ||
          a.completion_pct - b.completion_pct,
      ),
    [plans],
  );

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!fullName.trim() || !startDate) return;
    setSaving(true);
    setError(null);
    try {
      await createOnboardingPlan({
        full_name: fullName.trim(),
        start_date: startDate,
        role: role.trim() || undefined,
        template_name: templateName || undefined,
      });
      setFullName("");
      setStartDate("");
      setRole("");
      setTemplateName("");
      setShowCreate(false);
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create plan");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="flex flex-col h-full bg-surface">
      <main className="flex-1 overflow-y-auto">
        <div className="max-w-5xl mx-auto px-6 py-6">
          <div className="flex items-baseline justify-between mb-6 gap-4 flex-wrap">
            <div>
              <h1 className="text-xl font-semibold text-fg">Staff Onboarding</h1>
              <p className="text-sm text-fg-muted mt-0.5">
                Onboarding plans for new hires — progress, tasks, and the generated
                welcome brief.
              </p>
            </div>
            <button
              onClick={() => setShowCreate((s) => !s)}
              className="px-4 py-2 text-sm rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white font-medium"
            >
              {showCreate ? "Cancel" : "New plan"}
            </button>
          </div>

          {showCreate && (
            <form
              onSubmit={handleCreate}
              className="mb-6 rounded-xl border border-line bg-surface-elevated p-4 grid gap-3 sm:grid-cols-2"
            >
              <label className="flex flex-col gap-1 text-sm">
                <span className="text-fg-muted">Full name *</span>
                <input
                  value={fullName}
                  onChange={(e) => setFullName(e.target.value)}
                  required
                  className="px-3 py-2 rounded-lg bg-surface-input border border-line focus:outline-none focus:border-indigo-500"
                />
              </label>
              <label className="flex flex-col gap-1 text-sm">
                <span className="text-fg-muted">Start date *</span>
                <input
                  type="date"
                  value={startDate}
                  onChange={(e) => setStartDate(e.target.value)}
                  required
                  className="px-3 py-2 rounded-lg bg-surface-input border border-line focus:outline-none focus:border-indigo-500"
                />
              </label>
              <label className="flex flex-col gap-1 text-sm">
                <span className="text-fg-muted">Role</span>
                <input
                  value={role}
                  onChange={(e) => setRole(e.target.value)}
                  placeholder="e.g. Fractional CFO"
                  className="px-3 py-2 rounded-lg bg-surface-input border border-line focus:outline-none focus:border-indigo-500"
                />
              </label>
              <label className="flex flex-col gap-1 text-sm">
                <span className="text-fg-muted">Template</span>
                <select
                  value={templateName}
                  onChange={(e) => setTemplateName(e.target.value)}
                  className="px-3 py-2 rounded-lg bg-surface-input border border-line focus:outline-none focus:border-indigo-500"
                >
                  <option value="">No template (blank plan)</option>
                  {templates.map((t) => (
                    <option key={t.name} value={t.name}>
                      {t.title}
                    </option>
                  ))}
                </select>
              </label>
              <div className="sm:col-span-2 flex justify-end">
                <button
                  type="submit"
                  disabled={saving || !fullName.trim() || !startDate}
                  className="px-4 py-2 text-sm rounded-lg bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white font-medium"
                >
                  {saving ? "Creating…" : "Create plan"}
                </button>
              </div>
            </form>
          )}

          {loading && <p className="text-fg-muted text-sm">Loading…</p>}
          {error && (
            <div className="p-3 rounded-lg bg-rose-500/10 border border-rose-500/30 text-rose-300 text-sm mb-4">
              {error}
            </div>
          )}
          {!loading && !error && plans.length === 0 && (
            <div className="rounded-xl border border-line bg-surface-elevated p-8 text-center">
              <p className="text-fg-muted text-sm">
                No onboarding plans yet. Create one above, or ask the Executive to
                onboard a new hire in chat.
              </p>
            </div>
          )}

          <div className="space-y-3">
            {sorted.map((plan) => {
              const meta = STATUS_META[plan.status] ?? STATUS_META.draft;
              return (
                <Link
                  key={plan.id}
                  href={`/staff-onboarding/${plan.id}`}
                  className="block rounded-xl border border-line bg-surface-elevated p-4 hover:border-indigo-500/50 transition-colors"
                >
                  <div className="flex items-center justify-between gap-3 mb-2 flex-wrap">
                    <div className="min-w-0">
                      <span className="font-medium text-fg">{plan.full_name}</span>
                      {plan.role && (
                        <span className="text-sm text-fg-muted"> — {plan.role}</span>
                      )}
                    </div>
                    <div className="flex items-center gap-2">
                      <span
                        className={`px-2 py-0.5 text-[11px] rounded-full border ${meta.cls}`}
                      >
                        {meta.label}
                      </span>
                      <span className="text-[11px] text-fg-subtle">
                        {PHASE_LABEL[plan.current_phase] ?? plan.current_phase}
                      </span>
                    </div>
                  </div>
                  <div className="flex items-center gap-3">
                    <ProgressBar pct={plan.completion_pct} />
                    <span className="text-xs text-fg-subtle tabular-nums w-10 text-right">
                      {plan.completion_pct}%
                    </span>
                  </div>
                  <div className="mt-1.5 text-[11px] text-fg-subtle">
                    Starts {plan.start_date}
                  </div>
                </Link>
              );
            })}
          </div>
        </div>
      </main>
    </div>
  );
}
