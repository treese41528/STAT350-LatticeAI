import { afterEach, describe, expect, it, vi } from "vitest";
import { postSSE } from "../api/sse";
import type { SSEEvent } from "../api/types";

function streamResponse(chunks: string[], init: ResponseInit = {}): Response {
  const encoder = new TextEncoder();
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  });
  return new Response(body, {
    status: 200,
    headers: { "Content-Type": "text/event-stream" },
    ...init,
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("postSSE parser", () => {
  it("parses event/data lines, ignores pings, handles split chunks", async () => {
    const chunks = [
      ": ping\n\n",
      'event: meta\ndata: {"conversationId":"c1","messageId":"m1"}\n\n',
      'event: tok', // event name split across chunks
      'en\ndata: {"text":"hel',
      'lo"}\n\n',
      'event: done\r\ndata: {"messageId":"m1","finishReason":"stop"}\r\n\r\n', // CRLF variant
    ];
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(streamResponse(chunks)));

    const events: SSEEvent[] = [];
    await postSSE("/api/chat", { message: "hi" }, { onEvent: (e) => events.push(e) });

    expect(events.map((e) => e.event)).toEqual(["meta", "token", "done"]);
    expect(events[1]).toEqual({ event: "token", data: { text: "hello" } });
  });

  it("joins multi-line data with newlines", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(streamResponse(['event: token\ndata: {"text":\ndata: "x"}\n\n'])),
    );
    const events: SSEEvent[] = [];
    await postSSE("/api/chat", {}, { onEvent: (e) => events.push(e) });
    expect(events).toEqual([{ event: "token", data: { text: "x" } }]);
  });

  it("throws an ApiError with the server's error body on non-2xx", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({ error: { code: "rate_limited", message: "Slow down", retryable: true } }),
          { status: 429, headers: { "Retry-After": "12", "Content-Type": "application/json" } },
        ),
      ),
    );
    await expect(postSSE("/api/chat", {}, { onEvent: () => {} })).rejects.toMatchObject({
      code: "rate_limited",
      retryable: true,
      status: 429,
      retryAfterSeconds: 12,
    });
  });

  it("sends X-Device-Id and credentials through apiFetch", async () => {
    const fetchMock = vi.fn().mockResolvedValue(streamResponse([]));
    vi.stubGlobal("fetch", fetchMock);
    await postSSE("/api/chat", {}, { onEvent: () => {} });
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(init.credentials).toBe("include");
    expect(new Headers(init.headers).get("X-Device-Id")).toBeTruthy();
  });
});
