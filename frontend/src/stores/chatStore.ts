import { create } from "zustand";
import * as api from "../api/client";
import { ApiError } from "../api/http";
import { postSSE } from "../api/sse";
import type { ConversationSummary, Message, SSEEvent } from "../api/types";
import { announce } from "../lib/announcer";
import { trackEvent } from "../api/events";

/**
 * Chat store.
 *
 * `applyEvent(e: SSEEvent)` is the heart: a testable reducer that folds the
 * typed SSE stream into state (see src/test/chatStore.test.ts, driven by
 * recorded fixtures).
 *
 * Token handling: `token` deltas append to a NON-reactive module buffer; a
 * rAF-throttled flush (>= 50ms apart) commits them, so only the streaming
 * bubble re-renders (message components are memoized; the flush replaces one
 * message object in one conversation array). Structural events (citations,
 * done, refusal, error) force a synchronous flush first so ordering is exact.
 */

export type StreamPhase = "idle" | "connecting" | "queued" | "retrieving" | "answering" | "deeper";

export interface StreamStage {
  stage: string;
  label: string;
  done: boolean;
}

export interface StreamState {
  phase: StreamPhase;
  conversationId: string | null;
  messageId: string | null;
  queuePosition: number | null;
  queueEtaSeconds: number | null;
  stages: StreamStage[];
  abort: AbortController | null;
  /** Set when this stream is a "dig deeper" run for an existing message. */
  deeperSourceId: string | null;
}

export interface ChatError {
  code: string;
  message: string;
  retryable: boolean;
}

const IDLE_STREAM: StreamState = {
  phase: "idle",
  conversationId: null,
  messageId: null,
  queuePosition: null,
  queueEtaSeconds: null,
  stages: [],
  abort: null,
  deeperSourceId: null,
};

interface ChatState {
  conversations: Record<string, ConversationSummary>;
  order: string[];
  activeId: string | null;
  messages: Record<string, Message[]>;
  stream: StreamState;
  error: ChatError | null;
  lastQuestion: string | null;
  conversationsLoaded: boolean;

  send: (question: string) => Promise<void>;
  digDeeper: (messageId: string) => Promise<void>;
  applyEvent: (e: SSEEvent) => void;
  stop: () => void;
  retry: () => void;
  newChat: () => void;
  loadConversations: () => Promise<void>;
  openConversation: (id: string) => Promise<void>;
  removeConversation: (id: string) => Promise<void>;
  rename: (id: string, title: string) => Promise<void>;
  submitFeedback: (
    messageId: string,
    feedback: { rating: "up" | "down"; tags: string[]; comment?: string },
  ) => Promise<void>;
  clearError: () => void;

  /** Internal (exposed for tests): set up optimistic state before streaming. */
  _prepareSend: (question: string) => void;
  _prepareDeeper: (sourceMessageId: string) => void;
  /** Internal: commit buffered tokens to state immediately. */
  _flushTokens: () => void;
  /** Internal: stream closed without done/error (network drop or abort). */
  _finalizeInterrupted: (aborted: boolean) => void;
}

// ---------------------------------------------------------------------------
// Non-reactive token buffer + rAF-throttled flush
// ---------------------------------------------------------------------------

let tokenBuffer = "";
let flushScheduled = false;
let lastFlushAt = 0;
const MIN_FLUSH_INTERVAL_MS = 50;

function scheduleFlush(flush: () => void): void {
  if (flushScheduled) return;
  flushScheduled = true;
  const raf: (cb: () => void) => void =
    typeof requestAnimationFrame === "function"
      ? (cb) => requestAnimationFrame(() => cb())
      : (cb) => void setTimeout(cb, 16);
  const wait = Math.max(0, MIN_FLUSH_INTERVAL_MS - (Date.now() - lastFlushAt));
  setTimeout(() => {
    raf(() => {
      flushScheduled = false;
      lastFlushAt = Date.now();
      flush();
    });
  }, wait);
}

// ---------------------------------------------------------------------------
// Pure helpers
// ---------------------------------------------------------------------------

let uidCounter = 0;
function uid(prefix: string): string {
  return `${prefix}-${Date.now().toString(36)}-${(uidCounter++).toString(36)}`;
}

function patchMessage(
  state: Pick<ChatState, "messages">,
  convId: string,
  msgId: string,
  patch: (m: Message) => Partial<Message>,
): Pick<ChatState, "messages"> | Record<string, never> {
  const list = state.messages[convId];
  if (!list) return {};
  const idx = list.findIndex((m) => m.id === msgId);
  if (idx === -1) return {};
  const next = list.slice();
  next[idx] = { ...next[idx], ...patch(next[idx]) };
  return { messages: { ...state.messages, [convId]: next } };
}

function sortOrder(conversations: Record<string, ConversationSummary>): string[] {
  return Object.values(conversations)
    .sort((a, b) => new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime())
    .map((c) => c.id);
}

// ---------------------------------------------------------------------------
// Store
// ---------------------------------------------------------------------------

export const useChatStore = create<ChatState>()((set, get) => ({
  conversations: {},
  order: [],
  activeId: null,
  messages: {},
  stream: IDLE_STREAM,
  error: null,
  lastQuestion: null,
  conversationsLoaded: false,

  // -- streaming ------------------------------------------------------------

  send: async (question) => {
    const trimmed = question.trim();
    if (trimmed === "" || get().stream.phase !== "idle") return;
    const wasDraft = get().activeId === null || get().activeId!.startsWith("draft-");
    const serverConvId = wasDraft ? null : get().activeId;
    get()._prepareSend(trimmed);
    const abort = get().stream.abort!;
    trackEvent("message_sent", { chars: trimmed.length, newConversation: serverConvId === null });
    try {
      await postSSE(
        "/api/chat",
        { conversationId: serverConvId, message: trimmed },
        { signal: abort.signal, onEvent: (e) => get().applyEvent(e) },
      );
      get()._finalizeInterrupted(false);
    } catch (err) {
      if (abort.signal.aborted) {
        get()._finalizeInterrupted(true);
      } else {
        get()._flushTokens();
        const apiErr = err instanceof ApiError ? err : null;
        get().applyEvent({
          event: "error",
          data: {
            code: apiErr?.code ?? "network",
            message:
              apiErr?.message ?? "Connection lost while streaming the answer. Please retry.",
            retryable: apiErr?.retryable ?? true,
          },
        });
      }
    }
  },

  digDeeper: async (messageId) => {
    if (get().stream.phase !== "idle") return;
    get()._prepareDeeper(messageId);
    const abort = get().stream.abort;
    if (!abort) return; // message not found
    trackEvent("deeper_requested", { messageId });
    try {
      await postSSE(`/api/messages/${encodeURIComponent(messageId)}/deeper`, {}, {
        signal: abort.signal,
        onEvent: (e) => get().applyEvent(e),
      });
      get()._finalizeInterrupted(false);
    } catch (err) {
      if (abort.signal.aborted) {
        get()._finalizeInterrupted(true);
      } else {
        const apiErr = err instanceof ApiError ? err : null;
        get().applyEvent({
          event: "error",
          data: {
            code: apiErr?.code ?? "network",
            message: apiErr?.message ?? "Connection lost during the deeper pass. Please retry.",
            retryable: apiErr?.retryable ?? true,
          },
        });
      }
    }
  },

  _prepareSend: (question) => {
    const now = new Date().toISOString();
    set((state) => {
      let convId = state.activeId;
      let conversations = state.conversations;
      if (!convId) {
        convId = uid("draft");
        conversations = {
          ...conversations,
          [convId]: {
            id: convId,
            title: question.length > 60 ? `${question.slice(0, 57)}…` : question,
            updatedAt: now,
            messageCount: 0,
          },
        };
      }
      const userMsg: Message = {
        id: uid("local-u"),
        role: "user",
        content: question,
        citations: [],
        resources: [],
        status: "complete",
        createdAt: now,
      };
      const assistantMsg: Message = {
        id: uid("local-a"),
        role: "assistant",
        content: "",
        citations: [],
        resources: [],
        status: "queued",
        createdAt: now,
      };
      const list = state.messages[convId] ?? [];
      return {
        conversations,
        order: sortOrder(conversations),
        activeId: convId,
        messages: { ...state.messages, [convId]: [...list, userMsg, assistantMsg] },
        error: null,
        lastQuestion: question,
        stream: {
          ...IDLE_STREAM,
          phase: "connecting",
          conversationId: convId,
          messageId: assistantMsg.id,
          abort: new AbortController(),
        },
      };
    });
  },

  _prepareDeeper: (sourceMessageId) => {
    const now = new Date().toISOString();
    set((state) => {
      const convId = state.activeId;
      if (!convId) return {};
      const list = state.messages[convId] ?? [];
      if (!list.some((m) => m.id === sourceMessageId)) return {};
      const placeholder: Message = {
        id: uid("local-d"),
        role: "assistant",
        content: "",
        citations: [],
        resources: [],
        status: "queued",
        createdAt: now,
      };
      const withDeeper = patchMessage(state, convId, sourceMessageId, () => ({
        deeper: { status: "running", stages: [] },
      }));
      const messages = (withDeeper as Pick<ChatState, "messages">).messages ?? state.messages;
      return {
        messages: { ...messages, [convId]: [...messages[convId], placeholder] },
        error: null,
        stream: {
          ...IDLE_STREAM,
          phase: "deeper",
          conversationId: convId,
          messageId: placeholder.id,
          abort: new AbortController(),
          deeperSourceId: sourceMessageId,
        },
      };
    });
  },

  applyEvent: (e) => {
    const flushNow = () => get()._flushTokens();

    switch (e.event) {
      case "meta": {
        flushNow();
        const { conversationId, messageId, title } = e.data;
        set((state) => {
          const { stream } = state;
          const oldConvId = stream.conversationId;
          if (!oldConvId || !stream.messageId) return {};

          let { conversations, messages, order, activeId } = state;

          // Re-key a draft conversation to its server id.
          if (oldConvId !== conversationId) {
            const summary = conversations[oldConvId];
            conversations = { ...conversations };
            delete conversations[oldConvId];
            conversations[conversationId] = {
              ...(summary ?? {
                title: "New conversation",
                updatedAt: new Date().toISOString(),
                messageCount: 0,
              }),
              id: conversationId,
            };
            messages = { ...messages };
            messages[conversationId] = messages[oldConvId] ?? [];
            delete messages[oldConvId];
            order = sortOrder(conversations);
            if (activeId === oldConvId) activeId = conversationId;
          }

          if (title) {
            conversations = {
              ...conversations,
              [conversationId]: { ...conversations[conversationId], title },
            };
          }

          // Adopt the server's message id for the streaming assistant message.
          const renamed = patchMessage(
            { messages },
            conversationId,
            stream.messageId,
            () => ({ id: messageId }),
          );
          messages = (renamed as Pick<ChatState, "messages">).messages ?? messages;

          return {
            conversations,
            messages,
            order,
            activeId,
            stream: { ...stream, conversationId, messageId },
          };
        });
        break;
      }

      case "queue": {
        const { position, etaSeconds } = e.data;
        const prev = get().stream.queuePosition;
        set((state) => ({
          stream: {
            ...state.stream,
            phase: state.stream.deeperSourceId ? "deeper" : "queued",
            queuePosition: position,
            queueEtaSeconds: etaSeconds ?? null,
          },
        }));
        if (prev !== position) announce(`You're number ${position} in line`);
        break;
      }

      case "status": {
        const { stage, label } = e.data;
        set((state) => {
          const stages = [
            ...state.stream.stages.map((s) => ({ ...s, done: true })),
            { stage, label, done: false },
          ];
          const stream = {
            ...state.stream,
            phase: state.stream.deeperSourceId ? ("deeper" as const) : ("retrieving" as const),
            queuePosition: null,
            stages,
          };
          if (state.stream.deeperSourceId && state.stream.conversationId) {
            const patched = patchMessage(
              state,
              state.stream.conversationId,
              state.stream.deeperSourceId,
              (m) => ({
                deeper: { status: "running", ...m.deeper, stages },
              }),
            );
            return { ...patched, stream };
          }
          return { stream };
        });
        break;
      }

      case "citations": {
        flushNow();
        const { citations } = e.data;
        set((state) => {
          const { conversationId, messageId } = state.stream;
          if (!conversationId || !messageId) return {};
          return patchMessage(state, conversationId, messageId, () => ({ citations }));
        });
        break;
      }

      case "resources": {
        flushNow();
        const { resources } = e.data;
        set((state) => {
          const { conversationId, messageId } = state.stream;
          if (!conversationId || !messageId) return {};
          return patchMessage(state, conversationId, messageId, () => ({ resources }));
        });
        break;
      }

      case "token": {
        const first = tokenBuffer === "" && get().stream.phase !== "answering";
        tokenBuffer += e.data.text;
        if (first) {
          // Commit the phase/status change immediately so the UI switches
          // from "thinking" to a streaming bubble without waiting for a flush.
          set((state) => {
            const { conversationId, messageId, deeperSourceId } = state.stream;
            if (!conversationId || !messageId) return {};
            const patched = patchMessage(state, conversationId, messageId, (m) =>
              m.status === "queued" ? { status: "streaming" } : {},
            );
            return {
              ...patched,
              stream: {
                ...state.stream,
                phase: deeperSourceId ? "deeper" : "answering",
                queuePosition: null,
                stages: state.stream.stages.map((s) => ({ ...s, done: true })),
              },
            };
          });
        }
        scheduleFlush(() => get()._flushTokens());
        break;
      }

      case "refusal": {
        flushNow();
        const { reason, message } = e.data;
        set((state) => {
          const { conversationId, messageId } = state.stream;
          if (!conversationId || !messageId) return {};
          return patchMessage(state, conversationId, messageId, () => ({
            status: "refused",
            refusal: { reason, message },
          }));
        });
        announce("The tutor declined this request.");
        break;
      }

      case "done": {
        flushNow();
        const { finishReason, finalText } = e.data;
        set((state) => {
          const { conversationId, messageId, deeperSourceId } = state.stream;
          if (!conversationId || !messageId) return { stream: IDLE_STREAM };

          let patched = patchMessage(state, conversationId, messageId, (m) => ({
            // done.finalText is canonical (post link-lint): replace streamed text.
            content: finalText ?? m.content,
            status:
              finishReason === "refusal" || m.status === "refused" ? "refused" : "complete",
          }));
          let messages = (patched as Pick<ChatState, "messages">).messages ?? state.messages;

          if (deeperSourceId) {
            patched = patchMessage({ messages }, conversationId, deeperSourceId, (m) => ({
              deeper: {
                status: "done",
                stages: (m.deeper?.stages ?? []).map((s) => ({ ...s, done: true })),
                resultMessageId: state.stream.messageId ?? undefined,
              },
            }));
            messages = (patched as Pick<ChatState, "messages">).messages ?? messages;
          }

          const summary = state.conversations[conversationId];
          const conversations = summary
            ? {
                ...state.conversations,
                [conversationId]: {
                  ...summary,
                  updatedAt: new Date().toISOString(),
                  messageCount: (messages[conversationId] ?? []).length,
                },
              }
            : state.conversations;

          return {
            messages,
            conversations,
            order: sortOrder(conversations),
            stream: IDLE_STREAM,
          };
        });
        announce("Answer ready");
        break;
      }

      case "error": {
        flushNow();
        const { code, message, retryable } = e.data;
        set((state) => {
          const { conversationId, messageId, deeperSourceId } = state.stream;
          let out: Record<string, unknown> = {
            error: { code, message, retryable },
            stream: IDLE_STREAM,
          };
          if (conversationId && messageId) {
            const patched = patchMessage(state, conversationId, messageId, () => ({
              status: "error",
            }));
            let messages = (patched as Pick<ChatState, "messages">).messages ?? state.messages;
            if (deeperSourceId) {
              const p2 = patchMessage({ messages }, conversationId, deeperSourceId, (m) => ({
                deeper: { stages: [], ...m.deeper, status: "error" },
              }));
              messages = (p2 as Pick<ChatState, "messages">).messages ?? messages;
            }
            out = { ...out, messages };
          }
          return out as Partial<ChatState>;
        });
        announce("Something went wrong. You can retry.");
        break;
      }
    }
  },

  _flushTokens: () => {
    if (tokenBuffer === "") return;
    const text = tokenBuffer;
    tokenBuffer = "";
    const { conversationId, messageId } = get().stream;
    if (!conversationId || !messageId) return;
    set((state) =>
      patchMessage(state, conversationId, messageId, (m) => ({ content: m.content + text })),
    );
  },

  _finalizeInterrupted: (aborted) => {
    const { stream } = get();
    if (stream.phase === "idle") return; // done/error already handled it
    get()._flushTokens();
    set((state) => {
      const { conversationId, messageId, deeperSourceId } = state.stream;
      if (!conversationId || !messageId) return { stream: IDLE_STREAM };
      const list = state.messages[conversationId] ?? [];
      const msg = list.find((m) => m.id === messageId);
      let messages = state.messages;
      if (msg && msg.content === "" && msg.status !== "refused") {
        // Nothing arrived — drop the placeholder bubble.
        messages = {
          ...messages,
          [conversationId]: list.filter((m) => m.id !== messageId),
        };
      } else if (msg && (msg.status === "streaming" || msg.status === "queued")) {
        const patched = patchMessage(state, conversationId, messageId, () => ({
          status: "complete",
        }));
        messages = (patched as Pick<ChatState, "messages">).messages ?? messages;
      }
      if (deeperSourceId) {
        const p2 = patchMessage({ messages }, conversationId, deeperSourceId, (m) => ({
          deeper: m.deeper
            ? { ...m.deeper, status: m.deeper.status === "done" ? "done" : "error" }
            : undefined,
        }));
        messages = (p2 as Pick<ChatState, "messages">).messages ?? messages;
      }
      return {
        messages,
        stream: IDLE_STREAM,
        error:
          aborted || state.error
            ? state.error
            : {
                code: "interrupted",
                message: "The connection was interrupted before the answer finished.",
                retryable: true,
              },
      };
    });
  },

  stop: () => {
    const { stream } = get();
    if (stream.phase === "idle") return;
    stream.abort?.abort();
    trackEvent("stream_stopped", {});
  },

  retry: () => {
    const state = get();
    if (state.stream.phase !== "idle" || !state.lastQuestion) return;
    const convId = state.activeId;
    if (convId) {
      // Drop the trailing failed exchange so we don't duplicate it.
      set((s) => {
        const list = s.messages[convId] ?? [];
        let end = list.length;
        if (end > 0 && list[end - 1].role === "assistant" && list[end - 1].status === "error") {
          end -= 1;
        }
        if (end > 0 && list[end - 1].role === "user" && list[end - 1].content === s.lastQuestion) {
          end -= 1;
        }
        return { messages: { ...s.messages, [convId]: list.slice(0, end) }, error: null };
      });
    }
    void get().send(state.lastQuestion);
  },

  newChat: () => {
    if (get().stream.phase !== "idle") get().stop();
    set({ activeId: null, error: null });
  },

  // -- conversations ----------------------------------------------------------

  loadConversations: async () => {
    try {
      const list = await api.listConversations();
      const conversations: Record<string, ConversationSummary> = {};
      for (const c of list) conversations[c.id] = c;
      set({ conversations, order: sortOrder(conversations), conversationsLoaded: true });
    } catch {
      set({ conversationsLoaded: true });
    }
  },

  openConversation: async (id) => {
    set({ activeId: id, error: null });
    if (get().messages[id]) return;
    try {
      const detail = await api.getConversation(id);
      set((state) => ({
        messages: { ...state.messages, [id]: detail.messages },
        conversations: {
          ...state.conversations,
          [id]: {
            id: detail.id,
            title: detail.title,
            updatedAt: detail.updatedAt,
            messageCount: detail.messageCount,
          },
        },
      }));
    } catch {
      set({
        error: { code: "load_failed", message: "Couldn't load that conversation.", retryable: false },
      });
    }
  },

  removeConversation: async (id) => {
    const prev = get();
    set((state) => {
      const conversations = { ...state.conversations };
      delete conversations[id];
      const messages = { ...state.messages };
      delete messages[id];
      return {
        conversations,
        messages,
        order: sortOrder(conversations),
        activeId: state.activeId === id ? null : state.activeId,
      };
    });
    try {
      if (!id.startsWith("draft-")) await api.deleteConversation(id);
    } catch {
      set({ conversations: prev.conversations, order: prev.order, messages: prev.messages });
    }
  },

  rename: async (id, title) => {
    const trimmed = title.trim();
    if (trimmed === "") return;
    const prevTitle = get().conversations[id]?.title;
    set((state) => ({
      conversations: {
        ...state.conversations,
        [id]: { ...state.conversations[id], title: trimmed },
      },
    }));
    try {
      if (!id.startsWith("draft-")) await api.patchConversation(id, { title: trimmed });
    } catch {
      if (prevTitle !== undefined) {
        set((state) => ({
          conversations: {
            ...state.conversations,
            [id]: { ...state.conversations[id], title: prevTitle },
          },
        }));
      }
    }
  },

  submitFeedback: async (messageId, feedback) => {
    const convId = get().activeId;
    if (convId) {
      set((state) => patchMessage(state, convId, messageId, () => ({ feedback })));
    }
    trackEvent("feedback_submitted", { messageId, rating: feedback.rating, tags: feedback.tags });
    try {
      await api.postFeedback(messageId, feedback);
    } catch {
      // Keep the optimistic state; feedback is best-effort.
    }
  },

  clearError: () => set({ error: null }),
}));

/** Test helper: reset module-level token buffer between tests. */
export function __resetTokenBufferForTests(): void {
  tokenBuffer = "";
  flushScheduled = false;
  lastFlushAt = 0;
}
