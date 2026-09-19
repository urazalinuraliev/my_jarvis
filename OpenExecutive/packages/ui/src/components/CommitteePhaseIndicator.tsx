"use client";

import { CommitteePhase } from "@/lib/api";

interface Props {
  phase: CommitteePhase | null;
}

const STEPS: { key: CommitteePhase; label: string }[] = [
  { key: "drafting", label: "Drafting" },
  { key: "reviewing", label: "Committee review" },
  { key: "finalizing", label: "Revising" },
];

export default function CommitteePhaseIndicator({ phase }: Props) {
  const activeIdx = phase ? STEPS.findIndex((s) => s.key === phase) : -1;

  return (
    <div className="flex items-center gap-2 text-xs text-fg-muted">
      {STEPS.map((step, i) => {
        const isActive = i === activeIdx;
        const isDone = i < activeIdx;
        return (
          <div key={step.key} className="flex items-center gap-2">
            <div
              className={
                "w-1.5 h-1.5 rounded-full " +
                (isActive
                  ? "bg-indigo-400 animate-pulse motion-reduce:animate-none"
                  : isDone
                  ? "bg-indigo-500/60"
                  : "bg-surface-input")
              }
            />
            <span
              className={
                isActive
                  ? "text-fg italic"
                  : isDone
                  ? "text-fg-muted"
                  : "text-fg-subtle"
              }
            >
              {step.label}
            </span>
            {i < STEPS.length - 1 && (
              <span className="text-fg-subtle">→</span>
            )}
          </div>
        );
      })}
    </div>
  );
}
