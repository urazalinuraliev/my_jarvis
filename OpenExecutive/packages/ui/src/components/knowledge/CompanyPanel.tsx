"use client";

import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  deleteDocument,
  getDocument,
  listDocuments,
  uploadDocument,
  type CompanyDoc,
  type CompanyDocContent,
} from "@/lib/api";

interface CompanyPanelProps {
  domains: string[];
}

const PROSE_CLASS =
  "prose prose-invert prose-sm max-w-none prose-p:text-fg prose-headings:text-fg prose-strong:text-fg prose-code:text-indigo-300 prose-code:bg-surface-overlay prose-code:px-1.5 prose-code:py-0.5 prose-code:rounded prose-code:text-xs prose-code:before:content-none prose-code:after:content-none prose-pre:bg-surface-overlay prose-pre:border prose-pre:border-line-strong prose-blockquote:border-line-strong prose-blockquote:text-fg-muted prose-ul:text-fg prose-ol:text-fg prose-li:marker:text-fg-muted prose-hr:border-line-strong prose-a:text-indigo-400 prose-a:no-underline hover:prose-a:underline prose-table:text-fg prose-th:text-fg prose-th:border-line-strong prose-td:border-line-strong";

export default function CompanyPanel({ domains }: CompanyPanelProps) {
  const [docs, setDocs] = useState<CompanyDoc[]>([]);
  const [isUploading, setIsUploading] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const [domain, setDomain] = useState("general");
  const [error, setError] = useState<string | null>(null);
  const [viewing, setViewing] = useState<CompanyDocContent | null>(null);
  const [viewLoading, setViewLoading] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    listDocuments()
      .then(setDocs)
      .catch(() => setError("Failed to load documents"));
  }, []);

  // Close the viewer modal on Escape.
  useEffect(() => {
    if (!viewing) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setViewing(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [viewing]);

  async function handleFile(file: File) {
    setIsUploading(true);
    setError(null);
    try {
      await uploadDocument(file, domain);
      const updated = await listDocuments();
      setDocs(updated);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Upload failed");
    } finally {
      setIsUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  }

  async function handleDelete(filename: string) {
    if (!confirm(`Delete "${filename}"? This removes it from the knowledge base.`)) return;
    setError(null);
    try {
      await deleteDocument(filename);
      setDocs((prev) => prev.filter((d) => d.filename !== filename));
    } catch {
      setError("Failed to delete document");
    }
  }

  async function handleView(filename: string) {
    setError(null);
    setViewLoading(filename);
    try {
      const doc = await getDocument(filename);
      setViewing(doc);
    } catch {
      setError("Failed to load document");
    } finally {
      setViewLoading(null);
    }
  }

  return (
    <div className="space-y-6 max-w-2xl">
      <div>
        <h2 className="text-base font-semibold text-fg">Company documents</h2>
        <p className="text-xs text-fg-muted mt-1">
          Uploaded files indexed into the company knowledge collection. The Executive
          retrieves from these alongside the built-in playbooks.
        </p>
      </div>

      {error && (
        <p className="text-xs text-red-400 bg-red-500/10 border border-red-500/20 rounded-lg px-3 py-2">
          {error}
        </p>
      )}

      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragOver(false);
          const f = e.dataTransfer.files[0];
          if (f) handleFile(f);
        }}
        className={`rounded-xl border-2 border-dashed p-8 text-center transition-colors ${
          dragOver
            ? "border-indigo-500 bg-indigo-500/5"
            : "border-line-strong hover:border-line-strong"
        }`}
      >
        <p className="text-sm text-fg-muted mb-4">
          Drop a file here, or choose a domain and browse
        </p>
        <div className="flex items-center justify-center gap-3 flex-wrap">
          <select
            value={domain}
            onChange={(e) => setDomain(e.target.value)}
            className="rounded-lg border border-line-strong bg-surface-elevated px-3 py-1.5 text-sm text-fg focus:outline-none focus:ring-2 focus:ring-indigo-500/50"
          >
            <option value="general">general</option>
            {domains.map((d) => (
              <option key={d} value={d}>
                {d}
              </option>
            ))}
          </select>
          <label className="cursor-pointer px-4 py-1.5 rounded-lg bg-surface-input hover:bg-surface-input text-fg text-sm font-medium transition-colors">
            Browse file
            <input
              ref={fileInputRef}
              type="file"
              className="hidden"
              accept=".pdf,.docx,.doc,.md,.txt"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) handleFile(f);
              }}
            />
          </label>
        </div>
        <p className="text-xs text-fg-subtle mt-3">PDF, DOCX, MD, TXT — up to 50 MB</p>
        {isUploading && (
          <p className="mt-3 text-xs text-indigo-400 animate-pulse">Indexing…</p>
        )}
      </div>

      {docs.length === 0 ? (
        <p className="text-sm text-fg-subtle text-center py-8">No documents uploaded yet.</p>
      ) : (
        <div className="space-y-2">
          <p className="text-xs font-semibold text-fg-muted uppercase tracking-widest mb-3">
            Uploaded documents
          </p>
          {docs.map((doc) => (
            <div
              key={doc.filename}
              className="flex items-center justify-between px-4 py-3 rounded-xl bg-surface-overlay/60 border border-line-strong/50"
            >
              <div>
                <p className="text-sm text-fg font-medium">{doc.filename}</p>
                <p className="text-xs text-fg-muted mt-0.5">
                  {(doc.size_bytes / 1024).toFixed(1)} KB
                  {" · "}
                  {new Date(doc.modified_at * 1000).toLocaleDateString()}
                </p>
              </div>
              <div className="flex items-center gap-1">
                <button
                  onClick={() => handleView(doc.filename)}
                  disabled={viewLoading === doc.filename}
                  className="text-xs text-indigo-400 hover:text-indigo-300 disabled:opacity-50 px-2 py-1 rounded transition-colors"
                >
                  {viewLoading === doc.filename ? "Loading…" : "View"}
                </button>
                <button
                  onClick={() => handleDelete(doc.filename)}
                  className="text-xs text-red-400 hover:text-red-300 px-2 py-1 rounded transition-colors"
                >
                  Delete
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {viewing && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
          onClick={() => setViewing(null)}
        >
          <div
            className="flex max-h-[85vh] w-full max-w-3xl flex-col rounded-2xl border border-line-strong bg-surface-elevated shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between gap-3 border-b border-line-strong/60 px-6 py-4">
              <div className="min-w-0">
                <p className="text-xs font-semibold uppercase tracking-widest text-indigo-400">
                  Company document
                </p>
                <h3 className="truncate text-base font-semibold text-fg">
                  {viewing.filename}
                </h3>
              </div>
              <button
                onClick={() => setViewing(null)}
                className="flex-shrink-0 rounded-lg px-3 py-1.5 text-xs text-fg-muted hover:bg-surface-overlay hover:text-fg transition-colors"
              >
                Close
              </button>
            </div>
            <div className={`flex-1 overflow-y-auto px-6 py-5 ${PROSE_CLASS}`}>
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{viewing.content}</ReactMarkdown>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
