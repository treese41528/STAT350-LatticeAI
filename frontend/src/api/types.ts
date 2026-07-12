/**
 * API CONTRACT — single source of truth shared with the backend.
 *
 * The backend's Pydantic schemas are built against this file. If you change
 * anything here, the backend schemas must change in the same commit (and vice
 * versa). Do not add/remove/rename fields casually.
 *
 * SSE event order per answer:
 *   meta -> queue* -> status* -> citations -> resources -> token* -> (refusal) -> done | error
 * Citations/resources always arrive BEFORE the first token.
 * When `done.data.finalText` is present it is canonical (post link-lint) and
 * must replace the streamed content in the store.
 */

export type Modality = "flipped" | "traditional" | "indy" | "online" | "winter" | "summer";

export interface Citation {
  n: number;
  source: "webbook" | "transcript";
  title: string;
  snippet: string;
  similarity: number;
  url?: string;
}

export interface Resource {
  kind:
    | "lecture"
    | "video"
    | "worksheet"
    | "simulation"
    | "syllabus"
    | "schedule"
    | "exam"
    | "catalog";
  title: string;
  url: string;
  meta?: string;
}

export type SSEEvent =
  | { event: "meta"; data: { conversationId: string; messageId: string; title?: string } }
  | { event: "queue"; data: { position: number; etaSeconds?: number; suggestOwnKey?: boolean } }
  | { event: "status"; data: { stage: string; label: string } }
  | { event: "citations"; data: { citations: Citation[] } }
  | { event: "resources"; data: { resources: Resource[] } }
  | { event: "token"; data: { text: string } }
  | {
      event: "refusal";
      data: { reason: "weak_retrieval" | "out_of_scope" | "integrity"; message: string };
    }
  | {
      event: "done";
      data: {
        messageId: string;
        finishReason: "stop" | "refusal" | "length" | "aborted";
        finalText?: string;
        flags?: { caveat?: boolean; refusal?: boolean; beyondScope?: boolean; linted?: boolean };
      };
    }
  | { event: "error"; data: { code: string; message: string; retryable: boolean } };

export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations: Citation[];
  resources: Resource[];
  status: "queued" | "streaming" | "complete" | "refused" | "error";
  refusal?: { reason: string; message: string };
  feedback?: { rating: "up" | "down"; tags: string[]; comment?: string };
  deeper?: {
    status: "running" | "done" | "error";
    stages: { stage: string; label: string; done: boolean }[];
    resultMessageId?: string;
  };
  createdAt: string;
}

export interface ConversationSummary {
  id: string;
  title: string;
  updatedAt: string;
  messageCount: number;
}

export interface AppConfig {
  courseName: string;
  term: string;
  welcome: string;
  starterQuestions: string[];
  modalities: Modality[];
  features: { digDeeper: boolean; byok?: boolean };
  maxMessageChars: number;
}
