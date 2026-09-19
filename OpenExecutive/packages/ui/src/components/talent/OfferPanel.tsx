"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import {
  Candidate,
  Offer,
  OPEN_OFFER_STATUSES,
  extendOffer,
  listOffers,
  recordOfferDecision,
} from "@/lib/api";
import { OFFER_STATUS_META } from "@/components/talent/stages";
import { workflowLink } from "@/components/talent/workflowLink";

/** Days-until-expiry copy for an extended offer; null when not applicable. */
function expiryCountdown(offer: Offer): { text: string; urgent: boolean } | null {
  if (offer.status !== "extended" || !offer.expires_at) return null;
  const ms = new Date(offer.expires_at).getTime() - Date.now();
  if (Number.isNaN(ms)) return null;
  const days = ms / 86_400_000;
  if (days < 0) return { text: "expired — record a decision", urgent: true };
  if (days < 1) return { text: "expires today", urgent: true };
  const whole = Math.floor(days);
  return { text: `expires in ${whole} day${whole === 1 ? "" : "s"}`, urgent: days <= 3 };
}

/** Offer lifecycle panel on the candidate detail page.
 *
 * Shows the candidate's current (or most recent) offer: status, terms, the
 * persisted package from the offer_approval workflow, and the lifecycle
 * actions — draft (workflow), mark extended, record the decision, start
 * onboarding. OE never sends the offer to the candidate; the actions here
 * record what the principal did. */
export function OfferPanel({
  candidate,
  onChanged,
}: {
  candidate: Candidate;
  /** Called after a lifecycle action so the parent can reload the candidate
   *  (accepting an offer moves them to `placed` server-side). */
  onChanged?: () => void;
}) {
  const [offers, setOffers] = useState<Offer[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [showPackage, setShowPackage] = useState(false);
  const [expiresInDays, setExpiresInDays] = useState("7");

  const load = useCallback(() => {
    listOffers({ candidateId: candidate.id })
      .then(setOffers)
      .catch((e) => setError(e instanceof Error ? e.message : "Failed to load offers"));
  }, [candidate.id]);

  useEffect(() => {
    load();
  }, [load]);

  const open = offers.find((o) => OPEN_OFFER_STATUSES.includes(o.status));
  // With no open offer, show the latest decided one as history.
  const offer = open ?? offers[offers.length - 1];
  const countdown = offer ? expiryCountdown(offer) : null;
  const hireReady = candidate.stage === "placed" || offers.some((o) => o.status === "accepted");

  async function act(fn: () => Promise<{ warnings?: string[]; side_effects?: string[] }>) {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const result = await fn();
      const messages = [...(result.warnings ?? []), ...(result.side_effects ?? [])];
      if (messages.length) setNotice(messages.join(" · "));
      load();
      onChanged?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Offer action failed");
    } finally {
      setBusy(false);
    }
  }

  const meta = offer ? OFFER_STATUS_META[offer.status] : null;

  return (
    <div className="mb-6">
      <div className="text-xs font-semibold text-fg-muted uppercase tracking-wide mb-2">
        Offer
      </div>
      <div className="rounded-xl border border-line bg-surface-elevated p-4 space-y-3">
        {error && (
          <div className="p-2 rounded-lg bg-rose-500/10 border border-rose-500/30 text-rose-300 text-xs">
            {error}
          </div>
        )}
        {notice && (
          <div className="p-2 rounded-lg bg-amber-500/10 border border-amber-500/30 text-amber-300 text-xs">
            {notice}
          </div>
        )}

        {!offer ? (
          <div className="flex items-center justify-between gap-3">
            <p className="text-sm text-fg-subtle">
              No offer yet. The workflow drafts terms against the comp band and
              requests hiring sign-off.
            </p>
            <Link
              href={workflowLink("offer_approval", { candidate_id: String(candidate.id) })}
              className="shrink-0 px-3 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-medium"
            >
              Draft offer
            </Link>
          </div>
        ) : (
          <>
            <div className="flex items-center gap-2 flex-wrap">
              {meta && (
                <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-medium ${meta.pill}`}>
                  {meta.label}
                </span>
              )}
              {countdown && (
                <span className={`text-xs ${countdown.urgent ? "text-rose-300" : "text-fg-muted"}`}>
                  {countdown.text}
                </span>
              )}
              {offer.note && <span className="text-xs text-fg-subtle truncate">{offer.note}</span>}
            </div>

            {offer.comp_summary && (
              <p className="text-sm text-fg-muted whitespace-pre-wrap">{offer.comp_summary}</p>
            )}

            {offer.package_md && (
              <div>
                <button
                  onClick={() => setShowPackage((v) => !v)}
                  className="text-xs text-indigo-300 hover:text-indigo-200"
                >
                  {showPackage ? "Hide offer package" : "Show offer package"}
                </button>
                {showPackage && (
                  <pre className="mt-2 p-3 rounded-lg bg-surface-input border border-line text-xs text-fg-muted whitespace-pre-wrap overflow-x-auto">
                    {offer.package_md}
                  </pre>
                )}
              </div>
            )}

            <div className="flex flex-wrap items-center gap-2">
              {(offer.status === "draft" || offer.status === "pending_approval") && (
                <>
                  <label className="flex items-center gap-1 text-xs text-fg-muted">
                    Expires in
                    <input
                      value={expiresInDays}
                      onChange={(e) => setExpiresInDays(e.target.value)}
                      className="w-12 px-2 py-1 rounded-lg bg-surface-input border border-line text-xs text-fg focus:outline-none focus:border-indigo-500"
                    />
                    days
                  </label>
                  <button
                    disabled={busy}
                    onClick={() =>
                      act(() =>
                        extendOffer(offer.id, {
                          expires_in_days: Math.max(1, Math.min(60, Number(expiresInDays) || 7)),
                        }),
                      )
                    }
                    className="px-3 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-medium disabled:opacity-50"
                    title="You sent the offer yourself — this records it and schedules expiry reminders."
                  >
                    Mark extended
                  </button>
                </>
              )}
              {offer.status === "extended" && (
                <>
                  <button
                    disabled={busy}
                    onClick={() => act(() => recordOfferDecision(offer.id, "accepted"))}
                    className="px-3 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-medium disabled:opacity-50"
                  >
                    Accepted
                  </button>
                  <button
                    disabled={busy}
                    onClick={() => act(() => recordOfferDecision(offer.id, "declined"))}
                    className="px-3 py-1.5 rounded-lg border border-rose-500/40 text-rose-300 hover:bg-rose-500/10 text-xs font-medium disabled:opacity-50"
                  >
                    Declined
                  </button>
                  <button
                    disabled={busy}
                    onClick={() => act(() => recordOfferDecision(offer.id, "expired"))}
                    className="px-3 py-1.5 rounded-lg border border-line text-fg-muted hover:bg-surface-overlay text-xs font-medium disabled:opacity-50"
                  >
                    Expired
                  </button>
                </>
              )}
              {OPEN_OFFER_STATUSES.includes(offer.status) && (
                <button
                  disabled={busy}
                  onClick={() => act(() => recordOfferDecision(offer.id, "rescinded"))}
                  className="px-3 py-1.5 rounded-lg border border-line text-fg-muted hover:bg-surface-overlay text-xs font-medium disabled:opacity-50"
                >
                  Rescind
                </button>
              )}
              {!open && !hireReady && (
                <Link
                  href={workflowLink("offer_approval", { candidate_id: String(candidate.id) })}
                  className="px-3 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-medium"
                >
                  Draft new offer
                </Link>
              )}
            </div>
          </>
        )}

        {hireReady && (
          <div className="flex items-center justify-between gap-3 pt-2 border-t border-line">
            <p className="text-xs text-fg-muted">
              Hired — add them to the roster and schedule 30/60/90 check-ins.
            </p>
            <Link
              href={workflowLink("new_hire_onboarding", { candidate_id: String(candidate.id) })}
              className="shrink-0 px-3 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-medium"
            >
              Start onboarding
            </Link>
          </div>
        )}
      </div>
    </div>
  );
}
