import type { IncomingMessage, ServerResponse } from "node:http";
import type { Plugin } from "vite";

/**
 * Mock API — makes `npm run dev` fully demo-able with no backend.
 * Implements /api/config, /api/health, /api/profile, /api/conversations,
 * /api/chat (SSE), /api/messages/:id/deeper (SSE), feedback and events.
 *
 * Enabled by `vite --mode mock` (the default `npm run dev`) or VITE_MOCK=1.
 */

const CONFIG = {
  courseName: "STAT 350",
  term: "Fall 2026",
  welcome:
    "I'm your Socratic study companion for Introduction to Statistics. I'll nudge you toward the answer with questions, hints, and pointers into the course webbook, lecture videos, and simulations — and I always cite my sources.",
  starterQuestions: [
    "Walk me through the 4 steps of a one-sample t-test.",
    "When do I use a pooled vs unpooled standard error?",
    "What does the Central Limit Theorem actually claim?",
    "How do I make a QQ plot in R and read it?",
  ],
  modalities: ["flipped", "traditional", "indy", "online", "winter"],
  features: { digDeeper: true },
  maxMessageChars: 4000,
};

const CITATIONS = [
  {
    n: 1,
    source: "webbook",
    title: "Chapter 8.2 — One-Sample t Procedures",
    snippet:
      "When sigma is unknown we estimate it with the sample standard deviation s, and the standardized statistic t = (x-bar - mu_0) / (s / sqrt(n)) follows a t distribution with n - 1 degrees of freedom, provided the population is normal or n is large.",
    similarity: 0.87,
    url: "https://treese41528.github.io/STAT350/Website/chapter8.html",
  },
  {
    n: 2,
    source: "webbook",
    title: "Chapter 8.4 — The Four-Step Hypothesis Testing Procedure",
    snippet:
      "Step 1 identifies and describes the parameter in context; Step 2 states H0 and Ha in symbols; Step 3 computes the test statistic, degrees of freedom, and p-value; Step 4 states the decision and conclusion using the alpha-level templates.",
    similarity: 0.81,
    url: "https://treese41528.github.io/STAT350/Website/chapter8.html",
  },
  {
    n: 3,
    source: "transcript",
    title: "Lecture 21 — t Tests in Practice (video transcript)",
    snippet:
      "...remember, we define critical values through UPPER tail probabilities in this course. So for a 95 percent interval you look up t sub 0.025 with n minus 1 degrees of freedom, and R's qt function needs lower.tail = FALSE...",
    similarity: 0.63,
    url: "https://treese41528.github.io/STAT350/Website/video-viewer.html#lecture21",
  },
];

const RESOURCES = [
  {
    kind: "lecture",
    title: "Chapter 8 — Inference for a Single Mean",
    url: "https://treese41528.github.io/STAT350/Website/chapter8.html",
    meta: "Webbook chapter",
  },
  {
    kind: "video",
    title: "Lecture 21: t Tests in Practice",
    url: "https://treese41528.github.io/STAT350/Website/video-viewer.html#lecture21",
    meta: "18 min",
  },
  {
    kind: "simulation",
    title: "Power Simulator (alpha, beta, n, effect size)",
    url: "https://treese41528.github.io/STAT350/ShinyApps/Power_Simulator.html",
    meta: "Shiny app",
  },
  {
    kind: "worksheet",
    title: "Worksheet 8B — One-sample t practice",
    url: "https://treese41528.github.io/STAT350/Website/worksheets.html",
    meta: "Practice problems",
  },
];

const ANSWER = String.raw`Before I hand you a recipe — what is the **parameter** here? If we're testing a claim about a population mean fill volume, say the machine targets 355 mL, take a second: is the quantity of interest $\bar{x}$ or $\mu$? (This distinction is the most common exam slip [2].)

Here's the full 4-step structure we use in this course, with the fill-volume example:

### Step 1 — Identify the parameter

$\mu$ = the true mean fill volume (in mL) of all cans filled by this machine. Note that it's the *population* mean — $\bar{x} = 353.8$ mL is its sample estimate, not the parameter [1].

### Step 2 — State the hypotheses

$$H_0: \mu = 355 \qquad H_a: \mu \neq 355$$

Two-sided, because "the machine is off target" doesn't specify a direction.

### Step 3 — Test statistic and p-value

With $\sigma$ unknown we use the one-sample $t$ statistic with $n - 1 = 39$ degrees of freedom [1]:

$$t = \frac{\bar{x} - \mu_0}{s/\sqrt{n}} = \frac{353.8 - 355}{2.4/\sqrt{40}} \approx -3.16$$

In R:

` + "```r" + String.raw`
x <- c(354.1, 352.9, 353.5, 355.0)  # ... your 40 observations
t.test(x, mu = 355, alternative = "two.sided")

# or by hand:
tstat <- (mean(x) - 355) / (sd(x) / sqrt(length(x)))
2 * pt(abs(tstat), df = length(x) - 1, lower.tail = FALSE)
` + "```" + String.raw`

Remember we define critical values through **upper-tail** probabilities: $t_{0.025, 39}$ satisfies $P(T > t_{0.025,39}) = 0.025$ [3].

### Step 4 — Decision and conclusion

> At the $\alpha = 0.05$ level, we **reject** the null hypothesis because the p-value ($\approx 0.003$) $<$ $\alpha$. There **is** sufficient evidence to suggest that the true mean fill volume differs from 355 mL.

Now back to you: which of the t-procedure **conditions** (randomness, normality or large $n$) would you check first here, and what plot would you use? [2]

**Source:** [Chapter 8 — Inference for a Single Mean](https://treese41528.github.io/STAT350/Website/chapter8.html) · [Lecture 21 video](https://treese41528.github.io/STAT350/Website/video-viewer.html#lecture21) · [Power Simulator](https://treese41528.github.io/STAT350/ShinyApps/Power_Simulator.html)`;

const DEEPER_ANSWER = String.raw`Digging deeper into *why* the $t$ distribution appears at all:

When $\sigma$ is known, $Z = \frac{\bar{X} - \mu}{\sigma/\sqrt{n}}$ is exactly standard normal for a normal population. Replacing $\sigma$ with the random quantity $S$ adds extra variability, and the resulting ratio follows a heavier-tailed distribution — Student's $t$ with $n-1$ degrees of freedom [1].

Two facts make this work for a normal sample:

1. $\bar{X}$ and $S^2$ are **independent** (a special property of the normal!), and
2. $\frac{(n-1)S^2}{\sigma^2} \sim \chi^2_{n-1}$.

Then

$$T = \frac{Z}{\sqrt{\chi^2_{n-1}/(n-1)}} \sim t_{n-1}$$

As $n \to \infty$, $S \to \sigma$ and the $t$ curve converges to the standard normal — which is why the two are nearly indistinguishable past $n \approx 30$. Try it visually in the CLT simulation [2].

>>> BEYOND STAT 350 SCOPE: Enrichment for curious learners; not required for this course. <<<

The independence of $\bar{X}$ and $S^2$ characterizes the normal distribution (Geary's theorem). For the full derivation, consider [STAT 41600 — Probability](https://catalog.purdue.edu/preview_course_nopop.php?catoid=7&coid=61896).

**Source:** [Chapter 8 — Inference for a Single Mean](https://treese41528.github.io/STAT350/Website/chapter8.html) · [CLT Simulation](https://treese41528.github.io/STAT350/ShinyApps/CLT.html)`;

const REFUSAL_MESSAGE =
  "This looks like a graded assessment question, so I can't hand over the answer. I'd be glad to walk through a parallel practice problem step by step, or quiz you on the underlying concept — which would you like?";

// ---------------------------------------------------------------------------

interface MockMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations: unknown[];
  resources: unknown[];
  status: string;
  createdAt: string;
}

interface MockConversation {
  id: string;
  title: string;
  updatedAt: string;
  messages: MockMessage[];
}

let convCounter = 0;
let msgCounter = 0;
const newConvId = () => `conv-${++convCounter}`;
const newMsgId = () => `msg-${++msgCounter}`;

function hoursAgo(h: number): string {
  return new Date(Date.now() - h * 3600_000).toISOString();
}

function seedConversations(): Map<string, MockConversation> {
  const map = new Map<string, MockConversation>();
  const c1: MockConversation = {
    id: newConvId(),
    title: "One-sample t-test walkthrough",
    updatedAt: hoursAgo(2),
    messages: [
      {
        id: newMsgId(),
        role: "user",
        content: "Walk me through the 4 steps of a one-sample t-test.",
        citations: [],
        resources: [],
        status: "complete",
        createdAt: hoursAgo(2.1),
      },
      {
        id: newMsgId(),
        role: "assistant",
        content: ANSWER,
        citations: CITATIONS,
        resources: RESOURCES,
        status: "complete",
        createdAt: hoursAgo(2),
      },
    ],
  };
  const c2: MockConversation = {
    id: newConvId(),
    title: "QQ plots in R",
    updatedAt: hoursAgo(80),
    messages: [
      {
        id: newMsgId(),
        role: "user",
        content: "How do I make a QQ plot in R?",
        citations: [],
        resources: [],
        status: "complete",
        createdAt: hoursAgo(80.2),
      },
      {
        id: newMsgId(),
        role: "assistant",
        content:
          "What are we comparing a QQ plot *against*? Think about that while you try:\n\n```r\nqqnorm(x)\nqqline(x)\n```\n\nIf the points hug the line, the normality condition is plausible [1].",
        citations: [CITATIONS[0]],
        resources: [RESOURCES[0]],
        status: "complete",
        createdAt: hoursAgo(80),
      },
    ],
  };
  map.set(c1.id, c1);
  map.set(c2.id, c2);
  return map;
}

const conversations = seedConversations();
let profileModality: string | null = null;

// ---------------------------------------------------------------------------

function readBody(req: IncomingMessage): Promise<string> {
  return new Promise((resolve, reject) => {
    let data = "";
    req.on("data", (chunk: Buffer) => {
      data += chunk.toString("utf8");
    });
    req.on("end", () => resolve(data));
    req.on("error", reject);
  });
}

function sendJson(res: ServerResponse, status: number, body: unknown): void {
  res.writeHead(status, { "Content-Type": "application/json" });
  res.end(JSON.stringify(body));
}

function chunkText(text: string, size = 24): string[] {
  const chunks: string[] = [];
  for (let i = 0; i < text.length; i += size) chunks.push(text.slice(i, i + size));
  return chunks;
}

interface SSEWriter {
  send: (event: string, data: unknown) => void;
  ping: () => void;
  end: () => void;
}

function openSSE(res: ServerResponse): SSEWriter {
  res.writeHead(200, {
    "Content-Type": "text/event-stream",
    "Cache-Control": "no-cache, no-transform",
    Connection: "keep-alive",
    "X-Accel-Buffering": "no",
  });
  return {
    send: (event, data) => {
      res.write(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`);
    },
    ping: () => {
      res.write(`: ping\n\n`);
    },
    end: () => res.end(),
  };
}

/** Play a scripted list of [delayMs, fn] steps, cancellable when req closes. */
function playScript(req: IncomingMessage, steps: [number, () => void][], onDone: () => void): void {
  let cancelled = false;
  let timer: NodeJS.Timeout | null = null;
  req.on("close", () => {
    cancelled = true;
    if (timer) clearTimeout(timer);
  });
  let i = 0;
  const next = () => {
    if (cancelled) return;
    if (i >= steps.length) {
      onDone();
      return;
    }
    const [delay, fn] = steps[i++];
    timer = setTimeout(() => {
      if (cancelled) return;
      fn();
      next();
    }, delay);
  };
  next();
}

function streamAnswer(
  req: IncomingMessage,
  res: ServerResponse,
  opts: { conversationId: string; refusal: boolean; deeper: boolean },
): void {
  const sse = openSSE(res);
  const messageId = newMsgId();
  const conv = conversations.get(opts.conversationId);

  const steps: [number, () => void][] = [];
  steps.push([
    100,
    () =>
      sse.send("meta", {
        conversationId: opts.conversationId,
        messageId,
        title: conv?.title,
      }),
  ]);
  steps.push([200, () => sse.send("queue", { position: 2, etaSeconds: 6 })]);
  steps.push([700, () => sse.send("queue", { position: 1, etaSeconds: 3 })]);
  steps.push([500, () => sse.ping()]);

  if (opts.deeper) {
    steps.push([300, () => sse.send("status", { stage: "planning", label: "Planning a deeper pass" })]);
    steps.push([900, () => sse.send("status", { stage: "retrieving", label: "Searching webbook + transcripts (wide net)" })]);
    steps.push([1100, () => sse.send("status", { stage: "reranking", label: "Re-ranking passages" })]);
    steps.push([800, () => sse.send("status", { stage: "synthesizing", label: "Synthesizing a longer answer" })]);
  } else {
    steps.push([300, () => sse.send("status", { stage: "retrieving", label: "Searching course materials" })]);
    steps.push([700, () => sse.send("status", { stage: "ranking", label: "Ranking the best passages" })]);
  }

  if (opts.refusal) {
    steps.push([600, () => sse.send("refusal", { reason: "integrity", message: REFUSAL_MESSAGE })]);
    steps.push([
      150,
      () =>
        sse.send("done", {
          messageId,
          finishReason: "refusal",
          flags: { refusal: true },
        }),
    ]);
  } else {
    const text = opts.deeper ? DEEPER_ANSWER : ANSWER;
    const cites = opts.deeper ? [CITATIONS[0], CITATIONS[1]] : CITATIONS;
    const resources = opts.deeper ? [RESOURCES[0], RESOURCES[2]] : RESOURCES;
    steps.push([250, () => sse.send("citations", { citations: cites })]);
    steps.push([120, () => sse.send("resources", { resources } )]);
    for (const chunk of chunkText(text)) {
      steps.push([18, () => sse.send("token", { text: chunk })]);
    }
    steps.push([
      250,
      () =>
        sse.send("done", {
          messageId,
          finishReason: "stop",
          finalText: text, // canonical post-lint text
          flags: { linted: true, beyondScope: opts.deeper },
        }),
    ]);

    if (conv) {
      conv.messages.push({
        id: messageId,
        role: "assistant",
        content: text,
        citations: cites,
        resources,
        status: "complete",
        createdAt: new Date().toISOString(),
      });
      conv.updatedAt = new Date().toISOString();
    }
  }

  playScript(req, steps, () => sse.end());
}

// ---------------------------------------------------------------------------

export function mockApiPlugin(): Plugin {
  return {
    name: "stat350-mock-api",
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        void (async () => {
          const url = (req.url ?? "").split("?")[0];
          const method = (req.method ?? "GET").toUpperCase();
          if (!url.startsWith("/api/")) {
            next();
            return;
          }

          // Simulate a small network latency for realism.
          await new Promise((r) => setTimeout(r, 120));

          if (url === "/api/config" && method === "GET") {
            sendJson(res, 200, CONFIG);
            return;
          }

          if (url === "/api/health" && method === "GET") {
            sendJson(res, 200, { status: "ok", queueDepth: 0 });
            return;
          }

          if (url === "/api/profile") {
            if (method === "PATCH") {
              const body = JSON.parse((await readBody(req)) || "{}") as {
                modality?: string | null;
              };
              profileModality = body.modality ?? null;
            }
            sendJson(res, 200, { modality: profileModality });
            return;
          }

          if (url === "/api/conversations" && method === "GET") {
            const list = [...conversations.values()]
              .sort((a, b) => b.updatedAt.localeCompare(a.updatedAt))
              .map((c) => ({
                id: c.id,
                title: c.title,
                updatedAt: c.updatedAt,
                messageCount: c.messages.length,
              }));
            sendJson(res, 200, list);
            return;
          }

          const convMatch = url.match(/^\/api\/conversations\/([^/]+)$/);
          if (convMatch) {
            const conv = conversations.get(decodeURIComponent(convMatch[1]));
            if (!conv) {
              sendJson(res, 404, {
                error: { code: "not_found", message: "Conversation not found", retryable: false },
              });
              return;
            }
            if (method === "GET") {
              sendJson(res, 200, {
                id: conv.id,
                title: conv.title,
                updatedAt: conv.updatedAt,
                messageCount: conv.messages.length,
                messages: conv.messages,
              });
              return;
            }
            if (method === "PATCH") {
              const body = JSON.parse((await readBody(req)) || "{}") as { title?: string };
              if (body.title) conv.title = body.title;
              sendJson(res, 200, {
                id: conv.id,
                title: conv.title,
                updatedAt: conv.updatedAt,
                messageCount: conv.messages.length,
              });
              return;
            }
            if (method === "DELETE") {
              conversations.delete(conv.id);
              res.writeHead(204);
              res.end();
              return;
            }
          }

          if (url === "/api/chat" && method === "POST") {
            const body = JSON.parse((await readBody(req)) || "{}") as {
              conversationId?: string | null;
              message?: string;
            };
            const message = body.message ?? "";
            let convId = body.conversationId ?? null;
            if (!convId || !conversations.has(convId)) {
              convId = newConvId();
              conversations.set(convId, {
                id: convId,
                title: message.length > 48 ? `${message.slice(0, 45)}…` : message || "New chat",
                updatedAt: new Date().toISOString(),
                messages: [],
              });
            }
            const conv = conversations.get(convId)!;
            conv.messages.push({
              id: newMsgId(),
              role: "user",
              content: message,
              citations: [],
              resources: [],
              status: "complete",
              createdAt: new Date().toISOString(),
            });
            const refusal = /answer key|exam answers|solution key|do my (quiz|exam)/i.test(message);
            streamAnswer(req, res, { conversationId: convId, refusal, deeper: false });
            return;
          }

          const deeperMatch = url.match(/^\/api\/messages\/([^/]+)\/deeper$/);
          if (deeperMatch && method === "POST") {
            const msgId = decodeURIComponent(deeperMatch[1]);
            const conv =
              [...conversations.values()].find((c) => c.messages.some((m) => m.id === msgId)) ??
              [...conversations.values()][0];
            if (!conv) {
              sendJson(res, 404, {
                error: { code: "not_found", message: "Message not found", retryable: false },
              });
              return;
            }
            streamAnswer(req, res, { conversationId: conv.id, refusal: false, deeper: true });
            return;
          }

          const feedbackMatch = url.match(/^\/api\/messages\/([^/]+)\/feedback$/);
          if (feedbackMatch && method === "POST") {
            await readBody(req);
            res.writeHead(204);
            res.end();
            return;
          }

          if (url === "/api/events" && method === "POST") {
            await readBody(req);
            res.writeHead(204);
            res.end();
            return;
          }

          sendJson(res, 404, {
            error: { code: "not_found", message: `No mock for ${method} ${url}`, retryable: false },
          });
        })().catch((err: unknown) => {
          sendJson(res, 500, {
            error: { code: "mock_error", message: String(err), retryable: true },
          });
        });
      });
    },
  };
}
