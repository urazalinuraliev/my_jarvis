"use client";

import Link from "next/link";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import BrandMark from "@/components/BrandMark";
import type { ActionTaken } from "@/lib/api";

interface MessageProps {
  role: "user" | "assistant";
  content: string;
  isStreaming?: boolean;
  // Inline action chips for assistant messages. Each chip represents a
  // side-effecting tool the Executive fired during this turn (DM sent,
  // workflow opened, person updated, alert flagged…). User messages
  // never have actions.
  actions?: ActionTaken[];
}

function ActionChip({ action }: { action: ActionTaken }) {
  const inner = (
    <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] bg-emerald-500/10 border border-emerald-500/30 text-emerald-300">
      <span aria-hidden="true" className="text-[10px]">✓</span>
      <span>{action.summary}</span>
    </span>
  );
  if (action.link) {
    return (
      <Link href={action.link} className="hover:opacity-80 transition-opacity">
        {inner}
      </Link>
    );
  }
  return inner;
}

export default function Message({ role, content, isStreaming, actions }: MessageProps) {
  if (role === "user") {
    return (
      <div className="flex justify-end mb-6">
        <div className="max-w-xl px-4 py-3 rounded-2xl rounded-tr-sm bg-surface-overlay text-fg text-sm leading-relaxed">
          <p className="whitespace-pre-wrap">{content}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex gap-3 sm:gap-4 mb-8">
      {/* Avatar */}
      <div className="flex-shrink-0 mt-1">
        <BrandMark size="md" />
      </div>

      {/* Content */}
      <div className="flex-1 min-w-0">
        <div className="text-xs text-fg-muted mb-2 font-medium tracking-wide uppercase">Executive</div>
        <div className="prose prose-invert prose-sm max-w-none
          prose-code:px-1.5 prose-code:py-0.5 prose-code:rounded prose-code:text-xs prose-code:bg-surface-overlay prose-code:before:content-none prose-code:after:content-none
          prose-pre:bg-surface-overlay prose-pre:border
          prose-a:text-accent prose-a:no-underline hover:prose-a:underline">
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            urlTransform={(url) => {
              // Block javascript: and data: URL schemes to prevent XSS via prompt injection
              if (/^(javascript|data|vbscript):/i.test(url)) return "";
              return url;
            }}
          >
            {content}
          </ReactMarkdown>
          {isStreaming && (
            <span className="inline-block w-0.5 h-4 bg-accent cursor-blink ml-0.5 align-text-bottom rounded-full" />
          )}
        </div>

        {actions && actions.length > 0 && (
          <div
            className="mt-3 flex flex-wrap gap-1.5"
            aria-label={`${actions.length} action${actions.length === 1 ? "" : "s"} taken`}
          >
            {actions.map((action, i) => (
              <ActionChip key={`${action.tool}-${i}`} action={action} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
