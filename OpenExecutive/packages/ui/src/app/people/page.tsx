"use client";

import Link from "next/link";
import { type ReactNode, useEffect, useRef, useState } from "react";

import { useAskOEFormContext } from "@/components/askoe/AskOEContext";
import { createPerson, listPeople, type PageFormField, type Person } from "@/lib/api";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const ALL_SCOPES = [
  { value: "spend_lt_2k", label: "Spend <$2K", hint: "Receives proposals for any spend under $2K." },
  { value: "spend_lt_10k", label: "Spend <$10K", hint: "Receives proposals for spend under $10K." },
  { value: "spend_gt_10k", label: "Spend >$10K", hint: "Receives proposals for spend over $10K." },
  { value: "hiring_signoff", label: "Hiring", hint: "Receives proposals related to hiring decisions." },
  { value: "vendor_onboarding", label: "Vendors", hint: "Receives proposals for vendor contracts." },
  { value: "customer_credit", label: "Credit", hint: "Receives proposals involving credit or debt." },
  { value: "legal_sign", label: "Legal", hint: "Receives proposals with legal implications." },
  { value: "board_comms", label: "Board", hint: "Receives proposals before board communications." },
  { value: "wildcard", label: "All (wildcard)", hint: "Receives anything no one else is scoped for — usually the founder." },
];

const CHANNELS = ["any", "slack", "discord", "telegram", "email"];

// ---------------------------------------------------------------------------
// PersonCard (unchanged from read-only)
// ---------------------------------------------------------------------------

function ScopePill({ scope }: { scope: string }) {
  const entry = ALL_SCOPES.find((s) => s.value === scope);
  const label = entry?.label ?? scope;
  const isStar = scope === "wildcard";
  return (
    <span
      className={`inline-block px-1.5 py-0.5 rounded border text-[10px] font-medium ${
        isStar
          ? "bg-indigo-500/20 text-indigo-300 border-indigo-500/30"
          : "bg-surface-input/40 text-fg-muted border-line"
      }`}
    >
      {label}
    </span>
  );
}

function PersonCard({ person }: { person: Person }) {
  return (
    <Link
      href={`/people/${person.id}`}
      className="block rounded-xl border border-line bg-surface-elevated hover:bg-surface-overlay transition-colors p-4 group"
    >
      <div className="flex items-start justify-between gap-2 mb-2">
        <div>
          <div className="text-sm font-semibold text-fg group-hover:text-indigo-300 transition-colors flex items-center gap-2">
            {person.full_name}
            {person.is_principal && (
              <span className="inline-block px-1.5 py-0.5 rounded border text-[10px] font-medium bg-violet-500/20 text-violet-300 border-violet-500/30">
                Principal
              </span>
            )}
          </div>
          <div className="text-xs text-fg-muted mt-0.5">{person.role || "—"}</div>
        </div>
        <div className="flex-shrink-0 text-xs text-fg-muted capitalize">{person.preferred_channel}</div>
      </div>
      <div className="text-xs text-fg-muted mb-2">SLA: {person.response_sla_hours}h</div>
      {person.authority_scope.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {person.authority_scope.map((s) => (
            <ScopePill key={s} scope={s} />
          ))}
        </div>
      )}
    </Link>
  );
}

// ---------------------------------------------------------------------------
// Add Person modal
// ---------------------------------------------------------------------------

interface AddPersonModalProps {
  onCreated: (p: Person) => void;
  onClose: () => void;
}

const BLANK_FORM = {
  full_name: "",
  role: "",
  is_principal: false,
  email: "",
  slack_user_id: "",
  telegram_chat_id: "",
  discord_user_id: "",
  preferred_channel: "any",
  response_sla_hours: "24",
  authority_scope: [] as string[],
};

function DisclosureSection({
  label,
  open,
  onToggle,
  children,
}: {
  label: string;
  open: boolean;
  onToggle: () => void;
  children: ReactNode;
}) {
  return (
    <div className="border-t border-line pt-2">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        className="flex items-center justify-between w-full py-1.5 text-xs font-medium text-fg-muted hover:text-fg transition-colors"
      >
        <span>{label}</span>
        <span aria-hidden="true" className="text-fg-subtle text-[10px]">{open ? "▲" : "▼"}</span>
      </button>
      {open && <div className="pt-2 space-y-3">{children}</div>}
    </div>
  );
}

const SCOPE_VALUES = ALL_SCOPES.map((s) => s.value);

function AddPersonModal({ onCreated, onClose }: AddPersonModalProps) {
  const [form, setForm] = useState(BLANK_FORM);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [showContact, setShowContact] = useState(false);
  const [showAuthority, setShowAuthority] = useState(false);
  const nameRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    nameRef.current?.focus();
  }, []);

  // Registered with Ask OE for the modal's lifetime — closing the modal
  // unregisters automatically (the hook's cleanup runs on unmount).
  const { suggestedCls, clearSuggested } = useAskOEFormContext({
    formId: "add_person",
    title: "Add person",
    description:
      "Adds a human the Executive coordinates with. Authority scopes determine which proposals route to them for approval.",
    getFields: (): PageFormField[] => [
      { name: "full_name", label: "Full name", type: "text", value: form.full_name, required: true },
      { name: "role", label: "Role", type: "text", value: form.role },
      {
        name: "is_principal",
        label: "This is me — Primary",
        type: "boolean",
        value: form.is_principal,
        description: "Marks the person as the primary decision-maker. Only for the user themselves.",
      },
      { name: "preferred_channel", label: "Preferred channel", type: "select", options: CHANNELS, value: form.preferred_channel },
      { name: "response_sla_hours", label: "Expected reply within (hours)", type: "number", value: Number(form.response_sla_hours) || 24 },
      { name: "email", label: "Email", type: "text", value: form.email },
      { name: "slack_user_id", label: "Slack user ID", type: "text", value: form.slack_user_id },
      { name: "discord_user_id", label: "Discord user ID", type: "text", value: form.discord_user_id },
      { name: "telegram_chat_id", label: "Telegram chat ID", type: "text", value: form.telegram_chat_id },
      {
        name: "authority_scope",
        label: "Approval authority",
        type: "json",
        value: form.authority_scope,
        description: `JSON array of scope tokens, each one of: ${SCOPE_VALUES.join(", ")}.`,
      },
    ],
    applyPatch: (values) => {
      const prior = { form, showContact, showAuthority };
      const applied: string[] = [];
      const skipped: string[] = [];
      const next = { ...form };
      for (const [key, raw] of Object.entries(values)) {
        switch (key) {
          case "full_name":
          case "role":
          case "email":
          case "slack_user_id":
          case "discord_user_id":
          case "telegram_chat_id":
            if (typeof raw !== "string") skipped.push(key);
            else { next[key] = raw; applied.push(key); }
            break;
          case "is_principal":
            if (typeof raw !== "boolean") skipped.push(key);
            else { next.is_principal = raw; applied.push(key); }
            break;
          case "preferred_channel":
            if (typeof raw === "string" && CHANNELS.includes(raw)) {
              next.preferred_channel = raw;
              applied.push(key);
            } else skipped.push(key);
            break;
          case "response_sla_hours": {
            const n = Number(raw);
            if (Number.isFinite(n) && n >= 1) {
              next.response_sla_hours = String(Math.round(n));
              applied.push(key);
            } else skipped.push(key);
            break;
          }
          case "authority_scope": {
            const arr = Array.isArray(raw)
              ? raw.filter((s): s is string => typeof s === "string" && SCOPE_VALUES.includes(s))
              : null;
            // Empty after filtering means no proposed scope was recognized —
            // skip rather than silently wiping every existing scope.
            if (arr !== null && arr.length > 0) { next.authority_scope = arr; applied.push(key); }
            else skipped.push(key);
            break;
          }
          default:
            skipped.push(key);
        }
      }
      setForm(next);
      // Open the disclosures so the suggested values are visible to review.
      if (applied.some((k) => ["email", "slack_user_id", "discord_user_id", "telegram_chat_id", "preferred_channel", "response_sla_hours"].includes(k))) {
        setShowContact(true);
      }
      if (applied.includes("authority_scope")) setShowAuthority(true);
      return {
        applied,
        skipped,
        undo: () => {
          setForm(prior.form);
          setShowContact(prior.showContact);
          setShowAuthority(prior.showAuthority);
        },
      };
    },
  });

  function toggleScope(val: string) {
    setForm((f) => ({
      ...f,
      authority_scope: f.authority_scope.includes(val)
        ? f.authority_scope.filter((s) => s !== val)
        : [...f.authority_scope, val],
    }));
  }

  async function submit() {
    setSaving(true);
    setErr(null);
    try {
      const person = await createPerson({
        full_name: form.full_name.trim(),
        role: form.role.trim(),
        is_principal: form.is_principal,
        email: form.email.trim() || null,
        slack_user_id: form.slack_user_id.trim() || null,
        telegram_chat_id: form.telegram_chat_id.trim() || null,
        discord_user_id: form.discord_user_id.trim() || null,
        preferred_channel: form.preferred_channel,
        response_sla_hours: Number(form.response_sla_hours) || 24,
        authority_scope: form.authority_scope,
      });
      onCreated(person);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Create failed");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" onClick={saving ? undefined : onClose}>
      <div
        className="w-full max-w-lg bg-surface border border-line rounded-2xl shadow-2xl p-6 mx-4 max-h-[90vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="text-base font-semibold text-fg mb-4">Add person</h2>

        <div className="space-y-3">
          {/* Always-visible: the 10-second path */}
          <label className="text-xs text-fg-muted flex flex-col gap-1">
            Full name *
            <input
              ref={nameRef}
              value={form.full_name}
              onChange={(e) => { const v = e.target.value; setForm((f) => ({ ...f, full_name: v })); clearSuggested("full_name"); }}
              className={`px-3 py-2 rounded-lg bg-surface-input border border-line text-sm focus:outline-none focus:border-indigo-500 ${suggestedCls("full_name")}`}
              placeholder="Sarah Chen"
            />
          </label>

          <label className="text-xs text-fg-muted flex flex-col gap-1">
            Role
            <input
              value={form.role}
              onChange={(e) => { const v = e.target.value; setForm((f) => ({ ...f, role: v })); clearSuggested("role"); }}
              className={`px-3 py-2 rounded-lg bg-surface-input border border-line text-sm focus:outline-none focus:border-indigo-500 ${suggestedCls("role")}`}
              placeholder="CFO (fractional)"
            />
          </label>

          <label className="flex items-center gap-2.5 cursor-pointer select-none">
            <input
              type="checkbox"
              checked={form.is_principal}
              onChange={(e) => {
                const checked = e.target.checked;
                setForm((f) => ({ ...f, is_principal: checked }));
                if (checked) setShowAuthority(true);
              }}
              className="w-4 h-4 rounded accent-indigo-500"
            />
            <span className="text-sm text-fg">This is me — Primary</span>
            <span className="text-xs text-fg-muted">— marks you as the primary decision-maker</span>
          </label>

          {/* Contact & routing */}
          <DisclosureSection
            label="Contact & routing"
            open={showContact}
            onToggle={() => setShowContact((v) => !v)}
          >
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-xs text-fg-muted flex flex-col gap-1">
                  Preferred channel
                  <select
                    value={form.preferred_channel}
                    onChange={(e) => setForm((f) => ({ ...f, preferred_channel: e.target.value }))}
                    className="px-3 py-2 rounded-lg bg-surface-input border border-line text-sm focus:outline-none focus:border-indigo-500"
                  >
                    {CHANNELS.map((c) => (
                      <option key={c} value={c}>{c}</option>
                    ))}
                  </select>
                </label>
                <p className="text-[10px] text-fg-muted mt-1">
                  Proposals routed to this person are sent via {form.preferred_channel === "any" ? "any available channel" : form.preferred_channel}.
                </p>
              </div>
              <div>
                <label className="text-xs text-fg-muted flex flex-col gap-1">
                  Expected reply within
                  <div className="flex items-center gap-1.5">
                    <input
                      type="number"
                      min={1}
                      value={form.response_sla_hours}
                      onChange={(e) => setForm((f) => ({ ...f, response_sla_hours: e.target.value }))}
                      className="flex-1 px-3 py-2 rounded-lg bg-surface-input border border-line text-sm focus:outline-none focus:border-indigo-500"
                    />
                    <span className="text-xs text-fg-muted flex-shrink-0">hours</span>
                  </div>
                </label>
                <p className="text-[10px] text-fg-muted mt-1">
                  Items overdue in Today after {form.response_sla_hours || 24}h with no reply.
                </p>
              </div>
            </div>

            <label className="text-xs text-fg-muted flex flex-col gap-1">
              Email
              <input
                value={form.email}
                onChange={(e) => { const v = e.target.value; setForm((f) => ({ ...f, email: v })); clearSuggested("email"); }}
                className={`px-3 py-2 rounded-lg bg-surface-input border border-line text-sm focus:outline-none focus:border-indigo-500 ${suggestedCls("email")}`}
                placeholder="sarah@example.com"
              />
            </label>

            <label className="text-xs text-fg-muted flex flex-col gap-1">
              Slack user ID
              <input
                value={form.slack_user_id}
                onChange={(e) => setForm((f) => ({ ...f, slack_user_id: e.target.value }))}
                className="px-3 py-2 rounded-lg bg-surface-input border border-line text-sm focus:outline-none focus:border-indigo-500"
                placeholder="U01ABC123"
              />
            </label>

            <label className="text-xs text-fg-muted flex flex-col gap-1">
              Discord user ID
              <input
                value={form.discord_user_id}
                onChange={(e) => setForm((f) => ({ ...f, discord_user_id: e.target.value }))}
                className="px-3 py-2 rounded-lg bg-surface-input border border-line text-sm focus:outline-none focus:border-indigo-500"
                placeholder="123456789012345678"
              />
              <span className="text-[10px] text-fg-muted">
                Right-click your Discord username and &quot;Copy User ID&quot; (developer mode required).
              </span>
            </label>

            <label className="text-xs text-fg-muted flex flex-col gap-1">
              Telegram chat ID
              <input
                value={form.telegram_chat_id}
                onChange={(e) => setForm((f) => ({ ...f, telegram_chat_id: e.target.value }))}
                className="px-3 py-2 rounded-lg bg-surface-input border border-line text-sm focus:outline-none focus:border-indigo-500"
                placeholder="123456789"
              />
            </label>
          </DisclosureSection>

          {/* Approval authority */}
          <DisclosureSection
            label="Approval authority"
            open={showAuthority}
            onToggle={() => setShowAuthority((v) => !v)}
          >
            <div className="text-[10px] text-fg-muted mb-1.5">What this person approves</div>
            <div className="grid grid-cols-3 gap-1.5">
              {ALL_SCOPES.map(({ value, label, hint }) => {
                const active = form.authority_scope.includes(value);
                return (
                  <button
                    key={value}
                    type="button"
                    onClick={() => toggleScope(value)}
                    title={hint}
                    className={`px-2 py-1.5 rounded-lg border text-xs transition-colors text-left ${
                      active
                        ? "bg-indigo-600/30 border-indigo-500/50 text-indigo-300"
                        : "bg-surface-input border-line text-fg-muted hover:border-indigo-500/40"
                    }`}
                  >
                    <div className="font-medium">{label}</div>
                    <div className="text-[9px] leading-tight mt-0.5 opacity-70 line-clamp-2">{hint}</div>
                  </button>
                );
              })}
            </div>
          </DisclosureSection>

        </div>

        {err && <p className="text-xs text-rose-300 mt-3">{err}</p>}

        <div className="flex gap-2 mt-5">
          <button
            disabled={saving || !form.full_name.trim()}
            onClick={submit}
            className="flex-1 py-2 text-sm rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white disabled:opacity-50 font-medium"
          >
            {saving ? "Creating…" : "Add person"}
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

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function PeoplePage() {
  const [people, setPeople] = useState<Person[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showAdd, setShowAdd] = useState(false);

  function refresh() {
    setLoading(true);
    listPeople()
      .then(setPeople)
      .catch((e) => setError(e instanceof Error ? e.message : "Failed to load"))
      .finally(() => setLoading(false));
  }

  useEffect(() => { refresh(); }, []);

  return (
    <div className="flex flex-col h-full bg-surface">
      {showAdd && (
        <AddPersonModal
          onCreated={(p) => {
            setPeople((prev) => [...prev, p]);
            setShowAdd(false);
          }}
          onClose={() => setShowAdd(false)}
        />
      )}
      <main className="flex-1 overflow-y-auto">
        <div className="max-w-5xl mx-auto px-6 py-6">
          <div className="flex items-baseline justify-between mb-6">
            <div>
              <h1 className="text-xl font-semibold text-fg">People</h1>
              <p className="text-sm text-fg-muted mt-0.5">
                Humans the Executive coordinates with. Authority scopes determine who approves what.
              </p>
            </div>
            <button
              onClick={() => setShowAdd(true)}
              className="flex-shrink-0 px-4 py-2 text-sm rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white font-medium"
            >
              + Add person
            </button>
          </div>

          {loading && <p className="text-fg-muted text-sm">Loading…</p>}
          {error && (
            <div className="p-3 rounded-lg bg-rose-500/10 border border-rose-500/30 text-rose-300 text-sm mb-4">
              {error}
            </div>
          )}
          {!loading && !error && people.length === 0 && (
            <div className="rounded-xl border border-line bg-surface-elevated p-8 text-center">
              <p className="text-fg-muted text-sm mb-3">No people configured yet.</p>
              <button
                onClick={() => setShowAdd(true)}
                className="px-4 py-2 text-sm rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white"
              >
                Add your first person →
              </button>
            </div>
          )}

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {people.map((person) => (
              <PersonCard key={person.id} person={person} />
            ))}
          </div>
        </div>
      </main>
    </div>
  );
}
