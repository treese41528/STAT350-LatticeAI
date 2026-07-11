import { apiJson } from "./http";
import type { AppConfig, ConversationSummary, Message, Modality } from "./types";

/** Typed REST wrappers. All endpoints are same-origin under /api. */

export interface HealthStatus {
  status: string;
  queueDepth: number;
}

export interface ConversationDetail extends ConversationSummary {
  messages: Message[];
}

export function getConfig(): Promise<AppConfig> {
  return apiJson<AppConfig>("/api/config");
}

export function getHealth(): Promise<HealthStatus> {
  return apiJson<HealthStatus>("/api/health");
}

export function getProfile(): Promise<{ modality: Modality | null }> {
  return apiJson<{ modality: Modality | null }>("/api/profile");
}

export function patchProfile(modality: Modality | null): Promise<{ modality: Modality | null }> {
  return apiJson<{ modality: Modality | null }>("/api/profile", {
    method: "PATCH",
    body: JSON.stringify({ modality }),
  });
}

export function listConversations(): Promise<ConversationSummary[]> {
  return apiJson<ConversationSummary[]>("/api/conversations");
}

export function getConversation(id: string): Promise<ConversationDetail> {
  return apiJson<ConversationDetail>(`/api/conversations/${encodeURIComponent(id)}`);
}

export function patchConversation(id: string, patch: { title: string }): Promise<ConversationSummary> {
  return apiJson<ConversationSummary>(`/api/conversations/${encodeURIComponent(id)}`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
}

export function deleteConversation(id: string): Promise<void> {
  return apiJson<void>(`/api/conversations/${encodeURIComponent(id)}`, { method: "DELETE" });
}

export function postFeedback(
  messageId: string,
  feedback: { rating: "up" | "down"; tags: string[]; comment?: string },
): Promise<void> {
  return apiJson<void>(`/api/messages/${encodeURIComponent(messageId)}/feedback`, {
    method: "POST",
    body: JSON.stringify(feedback),
  });
}
