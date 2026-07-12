import { apiFetch, toApiError } from "./http";
import type { SSEEvent } from "./types";

/**
 * Hand-rolled SSE-over-POST client.
 *
 * EventSource cannot POST, so we parse the text/event-stream response of a
 * fetch by hand: `event:` / `data:` lines, blank-line dispatch, `:` comment
 * lines (keep-alive pings) ignored, multi-line data joined with "\n".
 *
 * No auto-reconnect by design — a chat answer is not resumable; on interrupt
 * the caller surfaces a Retry affordance instead.
 */

export interface PostSSEOptions {
  signal?: AbortSignal;
  onEvent: (event: SSEEvent) => void;
}

export async function postSSE(path: string, body: unknown, opts: PostSSEOptions): Promise<void> {
  const res = await apiFetch(path, {
    method: "POST",
    body: JSON.stringify(body),
    signal: opts.signal,
    headers: { Accept: "text/event-stream", "Content-Type": "application/json" },
  });
  if (!res.ok) throw await toApiError(res);
  if (!res.body) {
    throw new Error("Streaming not supported: response has no body");
  }

  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();

  let buffer = "";
  let eventName = "message";
  let dataLines: string[] = [];

  const dispatch = () => {
    if (dataLines.length === 0) {
      eventName = "message";
      return;
    }
    const name = eventName;
    const raw = dataLines.join("\n");
    eventName = "message";
    dataLines = [];
    let data: unknown;
    try {
      data = JSON.parse(raw);
    } catch {
      return; // malformed payload — skip rather than kill the stream
    }
    opts.onEvent({ event: name, data } as SSEEvent);
  };

  const handleLine = (line: string) => {
    if (line === "") {
      dispatch();
      return;
    }
    if (line.startsWith(":")) return; // comment / ping
    const colon = line.indexOf(":");
    const field = colon === -1 ? line : line.slice(0, colon);
    let value = colon === -1 ? "" : line.slice(colon + 1);
    if (value.startsWith(" ")) value = value.slice(1);
    if (field === "event") eventName = value;
    else if (field === "data") dataLines.push(value);
    // "id" and "retry" fields are intentionally ignored.
  };

  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += value;
      let nl: number;
      while ((nl = buffer.indexOf("\n")) !== -1) {
        let line = buffer.slice(0, nl);
        buffer = buffer.slice(nl + 1);
        if (line.endsWith("\r")) line = line.slice(0, -1);
        handleLine(line);
      }
    }
    // Flush any trailing partial line + pending event at EOF.
    if (buffer.length > 0) handleLine(buffer.replace(/\r$/, ""));
    dispatch();
  } finally {
    reader.releaseLock();
  }
}
