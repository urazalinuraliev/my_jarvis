"use client";

import { useCallback, useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  deleteSkill,
  getSkill,
  listSkills,
  searchSkills,
  type SkillDetail,
  type SkillMeta,
  type SkillSearchHit,
} from "@/lib/api";

export default function SkillsBrowser() {
  const [skills, setSkills] = useState<SkillMeta[]>([]);
  const [selected, setSelected] = useState<SkillDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchHits, setSearchHits] = useState<SkillSearchHit[] | null>(null);
  const [isSearching, setIsSearching] = useState(false);

  const load = useCallback(async () => {
    try {
      const data = await listSkills();
      setSkills(data);
    } catch {
      setError("Failed to load skills");
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function handleSelect(name: string) {
    setError(null);
    try {
      const data = await getSkill(name);
      setSelected(data);
    } catch {
      setError("Failed to load skill");
    }
  }

  async function handleDelete() {
    if (!selected) return;
    if (selected.source === "builtin") return;
    if (!confirm(`Delete skill "${selected.name}"? This cannot be undone.`)) return;
    try {
      await deleteSkill(selected.name);
      setSelected(null);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete skill");
    }
  }

  async function handleSearch(e: React.FormEvent) {
    e.preventDefault();
    if (!searchQuery.trim()) {
      setSearchHits(null);
      return;
    }
    setIsSearching(true);
    setError(null);
    try {
      const hits = await searchSkills(searchQuery.trim(), 10);
      setSearchHits(hits);
    } catch {
      setError("Search failed");
    } finally {
      setIsSearching(false);
    }
  }

  function clearSearch() {
    setSearchQuery("");
    setSearchHits(null);
  }

  const builtin = skills.filter((s) => s.source === "builtin");
  const userSkills = skills.filter((s) => s.source === "company");

  const groupByCategory = (items: SkillMeta[]) =>
    items.reduce<Record<string, SkillMeta[]>>((acc, s) => {
      (acc[s.category] ??= []).push(s);
      return acc;
    }, {});

  const builtinGrouped = groupByCategory(builtin);
  const userGrouped = groupByCategory(userSkills);

  return (
    <div className="max-w-5xl mx-auto px-6 py-8">
      {/* Search bar */}
      <form onSubmit={handleSearch} className="mb-6 flex gap-2">
        <input
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          placeholder="Search skills semantically (e.g. 'cash forecast for next quarter')"
          className="flex-1 rounded-lg border border-line-strong bg-surface-elevated px-3 py-2 text-sm text-fg placeholder-fg-subtle focus:outline-none focus:ring-2 focus:ring-indigo-500/50"
        />
        <button
          type="submit"
          disabled={isSearching}
          className="px-4 py-2 rounded-lg bg-indigo-500 hover:bg-indigo-400 disabled:opacity-40 text-white text-sm font-medium transition-colors"
        >
          {isSearching ? "Searching…" : "Search"}
        </button>
        {searchHits !== null && (
          <button
            type="button"
            onClick={clearSearch}
            className="px-3 py-2 border border-line-strong text-fg-muted hover:text-fg text-sm rounded-lg transition-colors"
          >
            Clear
          </button>
        )}
      </form>

      {error && (
        <p className="mb-4 text-xs text-red-400 bg-red-500/10 border border-red-500/20 rounded-lg px-3 py-2">
          {error}
        </p>
      )}

      <div className="flex gap-6">
        {/* Sidebar */}
        <div className="w-60 flex-shrink-0 space-y-5">
          {searchHits !== null ? (
            <div>
              <p className="text-xs font-semibold text-fg-muted uppercase tracking-widest mb-1.5 px-1">
                Results
              </p>
              {searchHits.length === 0 ? (
                <p className="text-xs text-fg-subtle px-1">No matches</p>
              ) : (
                searchHits.map((hit) => (
                  <button
                    key={`${hit.source}::${hit.name}`}
                    onClick={() => handleSelect(hit.name)}
                    className={`w-full text-left px-2.5 py-1.5 rounded-lg text-sm transition-colors ${
                      selected?.name === hit.name
                        ? "bg-surface-input text-fg"
                        : "text-fg-muted hover:text-fg hover:bg-surface-overlay"
                    }`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="truncate">{hit.name}</span>
                      <span className="text-[10px] text-fg-subtle flex-shrink-0">
                        {hit.score.toFixed(2)}
                      </span>
                    </div>
                  </button>
                ))
              )}
            </div>
          ) : (
            <>
              <SkillSection
                title="Built-in"
                grouped={builtinGrouped}
                selectedName={selected?.name}
                selectedSource={selected?.source}
                expectedSource="builtin"
                onSelect={handleSelect}
              />
              <SkillSection
                title="Yours"
                grouped={userGrouped}
                selectedName={selected?.name}
                selectedSource={selected?.source}
                expectedSource="company"
                onSelect={handleSelect}
                emptyMessage="Skills you save will appear here."
              />
            </>
          )}
        </div>

        {/* Detail pane */}
        <div className="flex-1 min-w-0">
          {selected ? (
            <SkillView skill={selected} onDelete={handleDelete} />
          ) : (
            <div className="flex flex-col items-center justify-center h-64 text-fg-subtle text-sm gap-2">
              <p>Select a skill to view its procedure.</p>
              <p className="text-xs text-fg-subtle">
                The Executive will call <code className="text-indigo-400">search_skills</code> when relevant.
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

interface SkillSectionProps {
  title: string;
  grouped: Record<string, SkillMeta[]>;
  selectedName: string | undefined;
  selectedSource: string | undefined;
  expectedSource: "builtin" | "company";
  onSelect: (name: string) => void;
  emptyMessage?: string;
}

function SkillSection({
  title,
  grouped,
  selectedName,
  selectedSource,
  expectedSource,
  onSelect,
  emptyMessage,
}: SkillSectionProps) {
  const categories = Object.keys(grouped).sort();
  const isEmpty = categories.length === 0;

  return (
    <div>
      <p className="text-xs font-semibold text-fg-muted uppercase tracking-widest mb-1.5 px-1">
        {title}
      </p>
      {isEmpty ? (
        <p className="text-xs text-fg-subtle px-1">{emptyMessage ?? "None"}</p>
      ) : (
        categories.map((cat) => (
          <div key={cat} className="mb-3">
            <p className="text-[11px] font-medium text-fg-subtle uppercase tracking-wider mb-0.5 px-1">
              {cat}
            </p>
            {grouped[cat].map((s) => (
              <button
                key={`${s.source}::${s.name}`}
                onClick={() => onSelect(s.name)}
                className={`w-full text-left px-2.5 py-1.5 rounded-lg text-sm transition-colors ${
                  selectedName === s.name && selectedSource === expectedSource
                    ? "bg-surface-input text-fg"
                    : "text-fg-muted hover:text-fg hover:bg-surface-overlay"
                }`}
              >
                {s.name}
              </button>
            ))}
          </div>
        ))
      )}
    </div>
  );
}

interface SkillViewProps {
  skill: SkillDetail;
  onDelete: () => void;
}

function SkillView({ skill, onDelete }: SkillViewProps) {
  return (
    <div className="flex flex-col gap-4 h-full">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-xs font-semibold text-indigo-400 uppercase tracking-widest">
              {skill.category}
            </span>
            <span className="text-[10px] uppercase tracking-wider text-fg-subtle px-2 py-0.5 border border-line rounded">
              {skill.source}
            </span>
          </div>
          <h2 className="text-base font-semibold text-fg mt-1 break-words">
            {skill.name}
          </h2>
          <p className="text-sm text-fg-muted mt-1">{skill.description}</p>
          <p className="text-xs text-fg-muted italic mt-1">
            When to use: {skill.when_to_use}
          </p>
        </div>
        {skill.source === "company" && (
          <button
            onClick={onDelete}
            className="px-3 py-1.5 rounded-lg border border-red-500/20 text-red-400 text-xs hover:bg-red-500/10 transition-colors flex-shrink-0"
          >
            Delete
          </button>
        )}
      </div>

      <div className="flex-1 h-[520px] rounded-xl border border-line-strong bg-surface-elevated px-6 py-5 overflow-y-auto prose prose-invert prose-sm max-w-none
        prose-p:text-fg prose-p:leading-relaxed
        prose-headings:text-fg prose-headings:font-semibold
        prose-strong:text-fg prose-strong:font-semibold
        prose-code:text-indigo-300 prose-code:bg-surface-overlay prose-code:px-1.5 prose-code:py-0.5 prose-code:rounded prose-code:text-xs prose-code:before:content-none prose-code:after:content-none
        prose-pre:bg-surface-overlay prose-pre:border prose-pre:border-line-strong
        prose-blockquote:border-line-strong prose-blockquote:text-fg-muted
        prose-ul:text-fg prose-ol:text-fg
        prose-li:marker:text-fg-muted
        prose-hr:border-line-strong
        prose-a:text-indigo-400 prose-a:no-underline hover:prose-a:underline
        prose-table:text-fg prose-th:text-fg prose-th:border-line-strong prose-td:border-line-strong">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{skill.body}</ReactMarkdown>
      </div>
    </div>
  );
}
