"use client";

import { useEffect, useRef, useState } from "react";
import { useSession } from "next-auth/react";
import Message from "./Message";
import BrandMark from "./BrandMark";
import CommitteePhaseIndicator from "./CommitteePhaseIndicator";
import Icon from "./Icon";
import InfoTip from "./InfoTip";
import {
  MAX_FILES_PER_TURN,
  mergePickedFiles,
} from "@/lib/file-attachments";
import {
  ActionTaken,
  ChatMessage,
  CommitteePhase,
  DebugEvent,
  getSuggestedPrompts,
  streamChat,
} from "@/lib/api";

interface ChatProps {
  onDebugEvent?: (event: DebugEvent) => void;
  initialMessages?: ChatMessage[];
  initialSessionId?: string;
  // Pre-populate the input box on first render. Used when entering chat
  // mode from a briefing item — the parent seeds a "Tell me about: …"
  // prompt that the user can edit before sending. Only consumed on mount
  // for a given session; subsequent changes are ignored to avoid clobbering
  // the user's typing.
  initialInput?: string;
  // When true AND `initialInput` is non-empty, submit it as the first turn
  // automatically instead of leaving it as a draft. Briefing handoffs
  // (Discuss / Approve / Dismiss / Edit&Approve) use this — the user has
  // already committed by clicking the action; making them hit Send again
  // is friction. One-shot per mount; ignored on subsequent prop updates.
  autoSubmitInitialInput?: boolean;
  onTurnComplete?: (sessionId: string) => void;
  onTurnStart?: () => void;
}

// Static fallbacks used only when the /chat/suggested-prompts fetch fails
// entirely (network error, aborted, etc). The backend always returns these
// same values on its own failure paths, so the happy path never shows them.
const SUGGESTED_PROMPTS = [
  "Where did we land on this quarter's priorities?",
  "Pull the team in on a decision I'm sitting on.",
  "Let's review the board update before it goes out.",
  "What's changed since our last sync?",
];

const FALLBACK_SUBTITLE =
  "Pick up where we left off — decisions to revisit, drafts to push forward, people to pull in.";

export default function Chat({ onDebugEvent, initialMessages, initialSessionId, initialInput, autoSubmitInitialInput, onTurnComplete, onTurnStart }: ChatProps) {
  const { data: session } = useSession();
  const firstName = session?.user?.name?.trim().split(/\s+/)[0];

  const [messages, setMessages] = useState<ChatMessage[]>(initialMessages ?? []);
  const [input, setInput] = useState(initialInput ?? "");
  const [isLoading, setIsLoading] = useState(false);
  const [sessionId, setSessionId] = useState<string | undefined>(initialSessionId);
  const [streamingContent, setStreamingContent] = useState("");
  // Inline action chips that arrived for the in-flight assistant message.
  // Reset on every turn; frozen onto the message at `done` event time.
  const [streamingActions, setStreamingActions] = useState<ActionTaken[]>([]);
  const [isConsulting, setIsConsulting] = useState(false);
  const [committeeEnabled, setCommitteeEnabled] = useState(false);
  const [committeePhase, setCommitteePhase] = useState<CommitteePhase | null>(null);
  const [suggested, setSuggested] = useState<string[]>([]);
  const [subtitle, setSubtitle] = useState<string>(FALLBACK_SUBTITLE);
  const [isLoadingPrompts, setIsLoadingPrompts] = useState(true);
  const [pendingFiles, setPendingFiles] = useState<File[]>([]);
  const [fileError, setFileError] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const adoptedSessionIdRef = useRef<string | undefined>(initialSessionId);

  useEffect(() => {
    const ctrl = new AbortController();
    getSuggestedPrompts(ctrl.signal)
      .then((r) => {
        if (r.prompts.length >= 4) setSuggested(r.prompts.slice(0, 4));
        else setSuggested(SUGGESTED_PROMPTS);
        if (r.subtitle) setSubtitle(r.subtitle);
        setIsLoadingPrompts(false);
      })
      .catch((err: unknown) => {
        // Abort on unmount is expected — don't flip loading off so we don't
        // briefly flash the static fallback before the component is gone.
        if (err instanceof DOMException && err.name === "AbortError") return;
        setSuggested(SUGGESTED_PROMPTS);
        setIsLoadingPrompts(false);
      });
    return () => ctrl.abort();
  }, []);

  // Sync when parent selects a different session (or clears for new chat).
  // Skip when the prop change is the parent echoing back an id this turn
  // already adopted locally — otherwise we'd wipe the just-streamed reply.
  useEffect(() => {
    if (initialSessionId === adoptedSessionIdRef.current) return;
    adoptedSessionIdRef.current = initialSessionId;
    setMessages(initialMessages ?? []);
    setSessionId(initialSessionId);
    setStreamingContent("");
  }, [initialSessionId]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, streamingContent]);

  // One-shot auto-submit of the initialInput on mount when the parent
  // requests it (briefing handoffs). Guarded by a ref so prop churn can't
  // re-fire it — mirrors the existing initialInput "adopt-once" contract.
  // We pass the prompt explicitly into handleSend so the state-clearing in
  // handleSend doesn't race with React batching `setInput("")` after the
  // submit reads it back.
  const didAutoSubmitRef = useRef(false);
  useEffect(() => {
    if (didAutoSubmitRef.current) return;
    if (!autoSubmitInitialInput) return;
    const seed = (initialInput ?? "").trim();
    if (!seed) return;
    didAutoSubmitRef.current = true;
    handleSend(seed);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function handleSend(text?: string) {
    const message = (text ?? input).trim();
    if ((!message && pendingFiles.length === 0) || isLoading) return;

    const filesForTurn = pendingFiles;
    const userBubbleContent = filesForTurn.length
      ? `${message}${message ? "\n\n" : ""}📎 ${filesForTurn.length} file${filesForTurn.length === 1 ? "" : "s"} attached`
      : message;

    setInput("");
    setPendingFiles([]);
    setFileError(null);
    setMessages((prev) => [...prev, { role: "user", content: userBubbleContent }]);
    setIsLoading(true);
    setStreamingContent("");
    setStreamingActions([]);
    setIsConsulting(false);
    setCommitteePhase(null);
    onTurnStart?.();

    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
    }

    try {
      let accumulated = "";
      // Local mirror of streamingActions so the closure builds the final
      // message without depending on the async setState applying first.
      const turnActions: ActionTaken[] = [];

      for await (const item of streamChat(message, sessionId, {
        committeeReview: committeeEnabled,
        files: filesForTurn,
      })) {
        if (item.type === "debug_event") {
          onDebugEvent?.(item);
          continue;
        }
        if (item.type === "chunk" && item.content) {
          accumulated += item.content;
          setIsConsulting(false);
          setStreamingContent(accumulated);
        } else if (item.type === "thinking") {
          setIsConsulting(true);
        } else if (item.type === "phase" && item.phase) {
          setCommitteePhase(item.phase);
          setIsConsulting(false);
        } else if (item.type === "committee_critique") {
          // Severity preview only; full critique stays server-side.
          // Nothing to render yet — phase indicator already reflects the
          // reviewing step. Hook left for future debug-panel surfacing.
        } else if (item.type === "action_taken") {
          turnActions.push(item);
          setStreamingActions([...turnActions]);
        } else if (item.type === "done") {
          if (item.session_id) {
            adoptedSessionIdRef.current = item.session_id;
            setSessionId(item.session_id);
            onTurnComplete?.(item.session_id);
          }
        } else if (item.type === "error") {
          throw new Error(item.message);
        }
      }

      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: accumulated,
          actions: turnActions.length > 0 ? turnActions : undefined,
        },
      ]);
      setStreamingContent("");
      setStreamingActions([]);
    } catch (err) {
      const detail = err instanceof Error ? err.message : String(err);
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: `Something went wrong: ${detail}` },
      ]);
      setStreamingContent("");
      setStreamingActions([]);
    } finally {
      setIsLoading(false);
      setIsConsulting(false);
      setCommitteePhase(null);
      textareaRef.current?.focus();
    }
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }

  function handleTextareaChange(e: React.ChangeEvent<HTMLTextAreaElement>) {
    setInput(e.target.value);
    e.target.style.height = "auto";
    e.target.style.height = Math.min(e.target.scrollHeight, 160) + "px";
  }

  function handleFilesPicked(e: React.ChangeEvent<HTMLInputElement>) {
    const picked = Array.from(e.target.files ?? []);
    // Reset the input so re-picking the same file re-fires onChange.
    e.target.value = "";
    if (picked.length === 0) return;
    const result = mergePickedFiles(pendingFiles, picked);
    setPendingFiles(result.files);
    setFileError(result.rejected.length > 0 ? result.rejected.join(" ") : null);
  }

  function removePendingFile(index: number) {
    setPendingFiles((prev) => prev.filter((_, i) => i !== index));
  }

  function formatFileSize(bytes: number): string {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }

  const isEmpty = messages.length === 0 && !isLoading && !streamingContent;

  return (
    <div className="flex flex-col h-full">
      {/* Messages */}
      <div className="flex-1 overflow-y-auto">
        <div className="max-w-3xl mx-auto px-4 sm:px-6 py-6 sm:py-8">
          {isEmpty ? (
            /* Empty state */
            <div className="flex flex-col items-center justify-center min-h-[60vh] text-center">
              <div className="mb-6">
                <BrandMark size="lg" />
              </div>
              <h2 className="text-xl font-semibold text-fg mb-2">
                {firstName
                  ? `Here's where we are, ${firstName}.`
                  : "Here's where we are."}
              </h2>
              <p className="text-fg-muted text-sm max-w-sm mb-10">
                {subtitle}
              </p>

              <div
                className="grid grid-cols-1 sm:grid-cols-2 gap-2 w-full max-w-lg"
                role="status"
                aria-busy={isLoadingPrompts}
                aria-label={isLoadingPrompts ? "Loading suggested prompts" : "Suggested prompts"}
              >
                {isLoadingPrompts
                  ? [0, 1, 2, 3].map((i) => (
                      <div
                        key={i}
                        aria-hidden
                        className="min-h-touch rounded-xl bg-surface-overlay/60 border border-line animate-pulse motion-reduce:animate-none"
                      />
                    ))
                  : suggested.map((prompt) => (
                      <button
                        type="button"
                        key={prompt}
                        onClick={() => handleSend(prompt)}
                        className="text-left px-4 py-3 min-h-touch rounded-xl bg-surface-overlay/60 border border-line hover:border-line-strong hover:bg-surface-overlay text-fg-muted hover:text-fg text-sm transition-all duration-150 cursor-pointer"
                      >
                        {prompt}
                      </button>
                    ))}
              </div>
            </div>
          ) : (
            <>
              {messages.map((msg, i) => (
                <Message
                  key={i}
                  role={msg.role}
                  content={msg.content}
                  actions={msg.role === "assistant" ? msg.actions : undefined}
                />
              ))}

              {streamingContent && (
                <Message
                  role="assistant"
                  content={streamingContent}
                  isStreaming
                  actions={streamingActions.length > 0 ? streamingActions : undefined}
                />
              )}

              {isLoading && !streamingContent && (
                <div className="flex gap-4 mb-8">
                  <div className="flex-shrink-0 mt-1">
                    <BrandMark size="md" />
                  </div>
                  <div className="flex-1 pt-1.5">
                    <div className="text-xs text-fg-muted mb-3 font-medium tracking-wide uppercase">Executive</div>
                    <div className="flex items-center gap-2 flex-wrap">
                      <div className="flex gap-1.5" aria-label="Thinking">
                        {[0, 1, 2].map((i) => (
                          <div
                            key={i}
                            className="w-1.5 h-1.5 bg-fg-muted rounded-full animate-bounce motion-reduce:animate-none"
                            style={{ animationDelay: `${i * 0.15}s` }}
                          />
                        ))}
                      </div>
                      {committeePhase ? (
                        <CommitteePhaseIndicator phase={committeePhase} />
                      ) : isConsulting ? (
                        <span className="text-xs text-fg-muted italic">Consulting specialists…</span>
                      ) : null}
                    </div>
                  </div>
                </div>
              )}
            </>
          )}
          <div ref={bottomRef} />
        </div>
      </div>

      {/* Input */}
      <div className="border-t border-line bg-surface px-4 sm:px-6 py-3 sm:py-4">
        <div className="max-w-3xl mx-auto">
          {pendingFiles.length > 0 && (
            <div className="flex flex-wrap gap-2 mb-2" aria-label="Pending attachments">
              {pendingFiles.map((f, i) => (
                <div
                  key={`${f.name}-${f.size}-${i}`}
                  className="flex items-center gap-2 bg-surface-overlay border border-line-strong rounded-lg pl-2.5 pr-1 py-1 text-xs text-fg-muted max-w-xs"
                >
                  <Icon name="paperclip" size="w-3 h-3" className="text-fg-muted" />
                  <span className="truncate" title={f.name}>{f.name}</span>
                  <span className="text-fg-muted/70 flex-shrink-0">{formatFileSize(f.size)}</span>
                  <button
                    type="button"
                    onClick={() => removePendingFile(i)}
                    aria-label={`Remove ${f.name}`}
                    className="flex-shrink-0 w-5 h-5 rounded hover:bg-line-strong/50 flex items-center justify-center cursor-pointer"
                  >
                    <Icon name="close" size="w-3 h-3" />
                  </button>
                </div>
              ))}
            </div>
          )}
          {fileError && (
            <p className="text-sm text-red-400 mb-2" role="alert">
              {fileError}
            </p>
          )}
          <div className="relative flex items-end gap-2 sm:gap-3 bg-surface-overlay/50 border border-line-strong rounded-2xl px-3 sm:px-4 py-3 focus-within:border-fg-muted transition-colors">
            <input
              ref={fileInputRef}
              type="file"
              multiple
              accept="image/png,image/jpeg,image/gif,image/webp,.pdf,.docx,.doc,.txt,.md,.csv"
              onChange={handleFilesPicked}
              className="hidden"
              aria-hidden="true"
            />
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              disabled={isLoading || pendingFiles.length >= MAX_FILES_PER_TURN}
              title={
                pendingFiles.length >= MAX_FILES_PER_TURN
                  ? `Limit ${MAX_FILES_PER_TURN} files per message`
                  : "Attach files or photos (PDF, DOCX, TXT, MD, CSV, images)"
              }
              aria-label="Attach files"
              className="flex-shrink-0 min-h-touch min-w-touch w-10 h-10 rounded-xl bg-surface-overlay border border-line-strong text-fg-muted hover:text-fg hover:border-line-strong disabled:opacity-30 disabled:cursor-not-allowed transition-all duration-150 flex items-center justify-center cursor-pointer"
            >
              <Icon name="paperclip" size="w-4 h-4" />
            </button>
            <textarea
              ref={textareaRef}
              value={input}
              onChange={handleTextareaChange}
              onKeyDown={handleKeyDown}
              placeholder="What's on your mind?"
              rows={1}
              disabled={isLoading}
              aria-label="Message"
              className="flex-1 bg-transparent text-fg placeholder:text-fg-muted text-sm sm:text-base leading-relaxed resize-none focus:outline-none disabled:opacity-50 max-h-40 overflow-y-auto"
              style={{ minHeight: "24px" }}
            />
            <button
              type="button"
              onClick={() => setCommitteeEnabled((v) => !v)}
              disabled={isLoading}
              title="Committee review: slower, higher-quality response — adversarial review pass before sending"
              aria-pressed={committeeEnabled}
              className={
                "flex-shrink-0 min-h-touch px-3 rounded-xl text-xs font-medium transition-all duration-150 border cursor-pointer " +
                (committeeEnabled
                  ? "bg-indigo-500/15 border-indigo-500/60 text-indigo-300 hover:bg-indigo-500/20"
                  : "bg-surface-overlay border-line-strong text-fg-muted hover:text-fg hover:border-line-strong") +
                " disabled:opacity-30 disabled:cursor-not-allowed"
              }
            >
              Committee
            </button>
            <button
              type="button"
              onClick={() => handleSend()}
              disabled={(!input.trim() && pendingFiles.length === 0) || isLoading}
              aria-label="Send message"
              className="flex-shrink-0 min-h-touch min-w-touch w-10 h-10 rounded-xl bg-indigo-500 hover:bg-indigo-400 disabled:opacity-30 disabled:cursor-not-allowed transition-all duration-150 flex items-center justify-center cursor-pointer"
            >
              <Icon name="arrow-send" size="w-4 h-4" className="text-white" />
            </button>
          </div>
          <p className="text-center text-xs text-fg-muted mt-2 inline-flex items-center justify-center gap-1.5 w-full">
            <span className="hidden sm:inline">Enter to send · Shift+Enter for new line</span>
            <span className="sm:hidden">Tap send</span>
            <InfoTip align="right">
              Your Executive routes your question to the right specialist
              behind the scenes — you don&apos;t pick which one.
            </InfoTip>
          </p>
        </div>
      </div>
    </div>
  );
}
