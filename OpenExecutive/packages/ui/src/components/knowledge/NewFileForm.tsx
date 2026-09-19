"use client";

import { useState } from "react";

interface NewFileFormProps {
  domains: string[];
  initialDomain: string;
  variant: "playbook" | "failure";
  onSave: (domain: string, filename: string, content: string) => Promise<void>;
  onCancel: () => void;
}

export default function NewFileForm({
  domains,
  initialDomain,
  variant,
  onSave,
  onCancel,
}: NewFileFormProps) {
  const [domain, setDomain] = useState(initialDomain);
  const [filename, setFilename] = useState("");
  const [content, setContent] = useState("");
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit() {
    const trimmed = filename.trim();
    const fullName = trimmed.endsWith(".md") ? trimmed : `${trimmed}.md`;
    if (!/^[a-zA-Z0-9_\-]+\.md$/.test(fullName)) {
      setError("Filename must be alphanumeric with dashes or underscores");
      return;
    }
    setIsSaving(true);
    setError(null);
    try {
      await onSave(domain, fullName, content);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to create file");
      setIsSaving(false);
    }
  }

  const title = variant === "failure" ? "New failure case" : "New playbook file";
  const placeholder =
    variant === "failure"
      ? "# Company X: <one-line failure summary>\n\n## Situation\n\n## What Happened\n\n## Root Cause\n\n## Key Decision Failures\n"
      : "# Title\n\nWrite your knowledge here…";

  return (
    <div className="flex flex-col gap-4">
      <h2 className="text-base font-semibold text-fg">{title}</h2>
      {error && (
        <p className="text-xs text-red-400 bg-red-500/10 border border-red-500/20 rounded-lg px-3 py-2">
          {error}
        </p>
      )}
      <div className="flex gap-3">
        <select
          value={domain}
          onChange={(e) => setDomain(e.target.value)}
          className="rounded-lg border border-line-strong bg-surface-elevated px-3 py-2 text-sm text-fg focus:outline-none focus:ring-2 focus:ring-indigo-500/50"
        >
          {domains.map((d) => (
            <option key={d} value={d}>
              {d}
            </option>
          ))}
        </select>
        <input
          value={filename}
          onChange={(e) => setFilename(e.target.value)}
          placeholder={variant === "failure" ? "my-failure-case.md" : "my_topic.md"}
          className="flex-1 rounded-lg border border-line-strong bg-surface-elevated px-3 py-2 text-sm text-fg placeholder-fg-subtle focus:outline-none focus:ring-2 focus:ring-indigo-500/50"
        />
      </div>
      <textarea
        value={content}
        onChange={(e) => setContent(e.target.value)}
        placeholder={placeholder}
        className="min-h-[400px] w-full rounded-xl border border-line-strong bg-surface-elevated px-4 py-3 text-sm text-fg font-mono focus:outline-none focus:ring-2 focus:ring-indigo-500/50 resize-none"
      />
      <div className="flex gap-3">
        <button
          onClick={handleSubmit}
          disabled={!filename.trim() || !content.trim() || isSaving}
          className="px-4 py-2 bg-indigo-500 hover:bg-indigo-400 disabled:opacity-40 text-white text-sm font-medium rounded-xl transition-colors"
        >
          {isSaving ? "Creating…" : "Create file"}
        </button>
        <button
          onClick={onCancel}
          className="px-4 py-2 border border-line-strong text-fg-muted hover:text-fg text-sm rounded-xl transition-colors"
        >
          Cancel
        </button>
      </div>
    </div>
  );
}
