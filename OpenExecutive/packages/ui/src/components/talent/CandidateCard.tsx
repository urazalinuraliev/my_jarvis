import Link from "next/link";
import { Candidate } from "@/lib/api";
import { StageBadge } from "./StageBadge";
import { fitScoreColor } from "./stages";

/** Compact candidate card used on the pipeline board and engagement detail. */
export function CandidateCard({ candidate }: { candidate: Candidate }) {
  const subtitle = [candidate.current_title, candidate.current_company]
    .filter(Boolean)
    .join(" · ");
  return (
    <Link
      href={`/talent/candidates/${candidate.id}`}
      className="block rounded-xl border border-line bg-surface-elevated hover:bg-surface-overlay transition-colors p-3 group"
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="text-sm font-semibold text-fg group-hover:text-indigo-300 truncate">
            {candidate.full_name}
          </div>
          {subtitle && (
            <div className="text-xs text-fg-muted truncate mt-0.5">{subtitle}</div>
          )}
        </div>
        <div
          className={`text-sm font-semibold tabular-nums ${fitScoreColor(candidate.fit_score)}`}
          title="Fit score"
        >
          {candidate.fit_score ?? "—"}
        </div>
      </div>
      <div className="mt-2">
        <StageBadge stage={candidate.stage} />
      </div>
    </Link>
  );
}
