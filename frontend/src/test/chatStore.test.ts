import { beforeEach, describe, expect, it } from "vitest";
import { useChatStore, __resetTokenBufferForTests } from "../stores/chatStore";
import type { SSEEvent } from "../api/types";
import happyFixture from "./fixtures/sse-happy.json";
import refusalFixture from "./fixtures/sse-refusal.json";
import errorFixture from "./fixtures/sse-error.json";
import deeperFixture from "./fixtures/sse-deeper.json";

/**
 * Highest-value test in the suite: drives the applyEvent reducer with
 * recorded SSE streams and asserts the resulting store state, including the
 * canonical finalText swap, refusals, errors, and the deeper flow.
 */

const happy = happyFixture as SSEEvent[];
const refusal = refusalFixture as SSEEvent[];
const errorStream = errorFixture as SSEEvent[];
const deeper = deeperFixture as SSEEvent[];

const initialState = useChatStore.getState();

function store() {
  return useChatStore.getState();
}

function feed(events: SSEEvent[]) {
  for (const e of events) store().applyEvent(e);
}

function assistantMessages(convId: string) {
  return (store().messages[convId] ?? []).filter((m) => m.role === "assistant");
}

beforeEach(() => {
  useChatStore.setState(initialState, true);
  __resetTokenBufferForTests();
});

describe("chatStore.applyEvent — happy path", () => {
  it("prepares optimistic state on send", () => {
    store()._prepareSend("Walk me through a one-sample t-test.");
    const s = store();
    expect(s.stream.phase).toBe("connecting");
    expect(s.activeId).toMatch(/^draft-/);
    const msgs = s.messages[s.activeId!];
    expect(msgs).toHaveLength(2);
    expect(msgs[0].role).toBe("user");
    expect(msgs[1].role).toBe("assistant");
    expect(msgs[1].status).toBe("queued");
  });

  it("re-keys the draft conversation and adopts server ids on meta", () => {
    store()._prepareSend("q");
    const draftId = store().activeId!;
    feed(happy.slice(0, 1)); // meta
    const s = store();
    expect(s.activeId).toBe("conv-100");
    expect(s.conversations["conv-100"]).toBeDefined();
    expect(s.conversations["conv-100"].title).toBe("One-sample t-test help");
    expect(s.conversations[draftId]).toBeUndefined();
    expect(s.messages[draftId]).toBeUndefined();
    expect(s.stream.messageId).toBe("m-200");
    expect(assistantMessages("conv-100")[0].id).toBe("m-200");
  });

  it("tracks queue position and stages", () => {
    store()._prepareSend("q");
    feed(happy.slice(0, 2)); // meta, queue#2
    expect(store().stream.phase).toBe("queued");
    expect(store().stream.queuePosition).toBe(2);
    expect(store().stream.queueEtaSeconds).toBe(8);
    feed([happy[2]]); // queue#1
    expect(store().stream.queuePosition).toBe(1);
    feed(happy.slice(3, 5)); // two status events
    const s = store();
    expect(s.stream.phase).toBe("retrieving");
    expect(s.stream.stages).toHaveLength(2);
    expect(s.stream.stages[0].done).toBe(true);
    expect(s.stream.stages[1].done).toBe(false);
    expect(s.stream.stages[1].label).toBe("Ranking the best passages");
  });

  it("attaches citations and resources BEFORE tokens", () => {
    store()._prepareSend("q");
    feed(happy.slice(0, 7)); // through resources
    const msg = assistantMessages("conv-100")[0];
    expect(msg.citations).toHaveLength(2);
    expect(msg.citations[0].source).toBe("webbook");
    expect(msg.resources).toHaveLength(1);
    expect(msg.content).toBe(""); // no tokens yet
  });

  it("streams tokens (buffered) and switches to answering", () => {
    store()._prepareSend("q");
    feed(happy.slice(0, 8)); // + first token
    expect(store().stream.phase).toBe("answering");
    expect(assistantMessages("conv-100")[0].status).toBe("streaming");
    feed(happy.slice(8, 10)); // more tokens
    store()._flushTokens();
    const content = assistantMessages("conv-100")[0].content;
    expect(content).toBe(
      "The parameter is $\\mu$, the population mean [1]. Which plot would you use to check normality? [2]",
    );
  });

  it("replaces streamed content with canonical finalText on done", () => {
    store()._prepareSend("q");
    feed(happy);
    const s = store();
    const msg = assistantMessages("conv-100")[0];
    expect(msg.status).toBe("complete");
    expect(msg.content).toContain("(link-linted)"); // finalText won
    expect(s.stream.phase).toBe("idle");
    expect(s.stream.abort).toBeNull();
    expect(s.conversations["conv-100"].messageCount).toBe(2);
    expect(s.order[0]).toBe("conv-100");
    expect(s.error).toBeNull();
  });
});

describe("chatStore.applyEvent — refusal", () => {
  it("marks the message refused with the reason and message", () => {
    store()._prepareSend("what are the exam answers");
    feed(refusal);
    const msg = assistantMessages("conv-101")[0];
    expect(msg.status).toBe("refused");
    expect(msg.refusal?.reason).toBe("integrity");
    expect(msg.refusal?.message).toMatch(/practice problem/);
    expect(store().stream.phase).toBe("idle");
    expect(store().error).toBeNull();
  });
});

describe("chatStore.applyEvent — error", () => {
  it("keeps partial content, marks message errored, sets retryable error", () => {
    store()._prepareSend("q");
    feed(errorStream);
    const msg = assistantMessages("conv-102")[0];
    expect(msg.status).toBe("error");
    expect(msg.content).toBe("Let's start by identifying "); // error flushed the buffer
    const err = store().error;
    expect(err?.code).toBe("upstream_timeout");
    expect(err?.retryable).toBe(true);
    expect(store().stream.phase).toBe("idle");
  });

  it("retry() strips the failed exchange and stores the question for resend", () => {
    store()._prepareSend("my question");
    feed(errorStream);
    expect(store().messages["conv-102"]).toHaveLength(2);
    expect(store().lastQuestion).toBe("my question");
  });
});

describe("chatStore.applyEvent — dig deeper", () => {
  function completeHappyAnswer() {
    store()._prepareSend("q");
    feed(happy);
  }

  it("runs the deeper flow: stages -> new message -> source marked done", () => {
    completeHappyAnswer();
    store()._prepareDeeper("m-200");

    let s = store();
    expect(s.stream.phase).toBe("deeper");
    expect(s.stream.deeperSourceId).toBe("m-200");
    expect(s.messages["conv-100"]).toHaveLength(3); // + placeholder
    expect(assistantMessages("conv-100")[0].deeper?.status).toBe("running");

    feed(deeper.slice(0, 4)); // meta + 3 status
    s = store();
    expect(s.stream.phase).toBe("deeper");
    const source = assistantMessages("conv-100")[0];
    expect(source.deeper?.stages).toHaveLength(3);
    expect(source.deeper?.stages[2].label).toBe("Synthesizing a longer answer");

    feed(deeper.slice(4)); // citations, resources, tokens, done
    s = store();
    const sourceAfter = assistantMessages("conv-100")[0];
    expect(sourceAfter.deeper?.status).toBe("done");
    expect(sourceAfter.deeper?.resultMessageId).toBe("m-300");
    expect(sourceAfter.deeper?.stages.every((st) => st.done)).toBe(true);

    const result = (s.messages["conv-100"] ?? []).find((m) => m.id === "m-300");
    expect(result?.status).toBe("complete");
    expect(result?.content).toBe(
      "Why does the t distribution appear? Because $S$ is random too [1].",
    );
    expect(result?.citations).toHaveLength(1);
    expect(s.stream.phase).toBe("idle");
  });
});

describe("chatStore — interruption", () => {
  it("finalizes a partially streamed message as complete on abort", () => {
    store()._prepareSend("q");
    feed(happy.slice(0, 9)); // through second token
    store()._flushTokens();
    store()._finalizeInterrupted(true);
    const msg = assistantMessages("conv-100")[0];
    expect(msg.status).toBe("complete");
    expect(msg.content.length).toBeGreaterThan(0);
    expect(store().stream.phase).toBe("idle");
    expect(store().error).toBeNull(); // user-initiated abort is not an error
  });

  it("drops the empty placeholder and surfaces a retryable error on network drop", () => {
    store()._prepareSend("q");
    feed(happy.slice(0, 5)); // no tokens yet
    store()._finalizeInterrupted(false);
    expect(assistantMessages("conv-100")).toHaveLength(0);
    expect(store().error?.retryable).toBe(true);
  });
});
