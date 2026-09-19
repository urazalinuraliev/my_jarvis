"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { WorkflowRunDetail, getWorkflowRun } from "@/lib/api";

function formatTimestamp(iso: string): string {
  return new Date(iso).toLocaleString();
}

export default function RunDetailPage() {
  const params = useParams<{ id: string }>();
  const runId = params?.id;
  const [run, setRun] = useState<WorkflowRunDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!runId) return;
    getWorkflowRun(runId)
      .then(setRun)
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, [runId]);

  const handleCopy = useCallback(async () => {
    if (!run?.artifact) return;
    try {
      await navigator.clipboard.writeText(run.artifact);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // ignore — clipboard API may be unavailable
    }
  }, [run]);

  const handleDownload = useCallback(() => {
    if (!run?.artifact) return;
    const blob = new Blob([run.artifact], { type: "text/markdown" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${run.workflow_name}-${run.run_id.slice(0, 8)}.md`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }, [run]);

  if (error) {
    return (
      <div className="flex flex-col h-full bg-surface text-fg items-center justify-center">
        <div className="text-sm text-red-400 mb-4">Error: {error}</div>
        <Link href="/jobs" className="text-sm text-fg-muted hover:text-fg">
          ← Back to jobs
        </Link>
      </div>
    );
  }

  if (!run) {
    return (
      <div className="flex flex-col h-full bg-surface text-fg-muted items-center justify-center text-sm">
        Loading…
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full bg-surface text-fg">
      <main className="flex-1 overflow-y-auto px-6 py-8">
        <div className="max-w-4xl mx-auto space-y-6">
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0">
              <h1 className="text-2xl font-semibold text-fg mb-1">
                {run.title}
              </h1>
              <div className="text-xs text-fg-muted">
                {run.workflow_name} · created {formatTimestamp(run.created_at)} ·
                status <StatusPill status={run.status} />
              </div>
            </div>
            {run.artifact && (
              <div className="flex items-center gap-2 flex-shrink-0">
                <button
                  type="button"
                  onClick={handleCopy}
                  className="text-xs text-fg-muted hover:text-fg transition px-3 py-1.5 rounded-md border border-line hover:bg-surface-overlay min-h-touch"
                >
                  {copied ? "Copied!" : "Copy"}
                </button>
                <button
                  type="button"
                  onClick={handleDownload}
                  className="text-xs text-fg-muted hover:text-fg transition px-3 py-1.5 rounded-md border border-line hover:bg-surface-overlay min-h-touch"
                >
                  Download .md
                </button>
              </div>
            )}
          </div>

          {run.status === "running" && (
            <div className="rounded-md border border-amber-500/30 bg-amber-500/5 px-4 py-3 text-sm text-amber-300">
              This run is still in progress. Refresh in a moment.
            </div>
          )}

          {run.status === "error" && (
            <div className="rounded-md border border-red-500/30 bg-red-500/5 px-4 py-3 text-sm text-red-300">
              <div className="font-medium mb-1">Run failed</div>
              <div className="text-xs">{run.error}</div>
            </div>
          )}

          {run.artifact && (
            <article className="prose prose-invert prose-sm max-w-none rounded-lg border border-line bg-surface/40 p-6
              prose-headings:text-fg prose-headings:font-semibold
              prose-p:text-fg prose-p:leading-relaxed
              prose-strong:text-fg
              prose-code:text-indigo-300 prose-code:bg-surface-overlay prose-code:px-1.5 prose-code:py-0.5 prose-code:rounded prose-code:before:content-none prose-code:after:content-none
              prose-pre:bg-surface-overlay prose-pre:border prose-pre:border-line-strong
              prose-blockquote:border-line-strong prose-blockquote:text-fg-muted
              prose-ul:text-fg prose-ol:text-fg
              prose-li:marker:text-fg-muted
              prose-hr:border-line-strong
              prose-a:text-indigo-400 prose-a:no-underline hover:prose-a:underline
              prose-table:text-fg prose-th:text-fg prose-th:border-line-strong prose-td:border-line-strong">
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={{
                  a: ({ node: _node, ...props }) => (
                    <a {...props} rel="noopener noreferrer nofollow" target="_blank" />
                  ),
                }}
              >
                {run.artifact}
              </ReactMarkdown>
            </article>
          )}

          <details className="rounded-md border border-line bg-surface/30 px-4 py-3 text-sm">
            <summary className="text-xs text-fg-muted cursor-pointer">
              Inputs
            </summary>
            <pre className="mt-3 text-xs text-fg whitespace-pre-wrap font-mono">
              {JSON.stringify(run.inputs, null, 2)}
            </pre>
          </details>
        </div>
      </main>
    </div>
  );
}

function StatusPill({ status }: { status: string }) {
  const color =
    status === "done"
      ? "text-emerald-400"
      : status === "error"
      ? "text-red-400"
      : "text-amber-400";
  return <span className={`${color} font-medium`}>{status}</span>;
}
