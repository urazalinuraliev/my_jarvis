import { CandidateStage, EngagementStatus } from "@/lib/api";
import { STAGE_META, STATUS_META } from "./stages";

export function StageBadge({ stage }: { stage: CandidateStage }) {
  const meta = STAGE_META[stage] ?? { label: stage, pill: "bg-zinc-500/20 text-zinc-300 border-zinc-500/30" };
  return (
    <span
      className={`inline-block px-1.5 py-0.5 rounded border text-[10px] font-medium ${meta.pill}`}
    >
      {meta.label}
    </span>
  );
}

export function StatusBadge({ status }: { status: EngagementStatus }) {
  const meta = STATUS_META[status] ?? {
    label: status,
    pill: "bg-zinc-500/20 text-zinc-300 border-zinc-500/30",
  };
  return (
    <span
      className={`inline-block px-1.5 py-0.5 rounded border text-[10px] font-medium ${meta.pill}`}
    >
      {meta.label}
    </span>
  );
}
