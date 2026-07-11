// End-to-end frontend smoke test against the real built app in mock mode.
// Starts the Vite mock dev server, drives the UI with a real browser, asserts
// the rendered DOM (formulas -> KaTeX, citations -> chips + popover link,
// resource cards -> correct hrefs, R code fence), and saves screenshots.
//
//   node e2e-smoke.mjs   (chromium via playwright must be installed)

import { spawn } from "node:child_process";
import { chromium } from "playwright";

const OUT = process.env.SHOT_DIR || "/tmp/claude-1000/-mnt-c-CommonFiles-STAT-350-General-Materials-STAT-350-Chatbot/5272558f-51d2-4aea-98b5-d8ded8f1e8ce/scratchpad";
const PORT = 5199;
const results = [];
const check = (name, ok, detail = "") => {
  results.push({ name, ok, detail });
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail ? "  — " + detail : ""}`);
};

const server = spawn("npx", ["vite", "--mode", "mock", "--port", String(PORT), "--strictPort"], {
  cwd: process.cwd(), stdio: "ignore", env: { ...process.env },
});

async function waitForServer(url, ms = 30000) {
  const deadline = Date.now() + ms;
  while (Date.now() < deadline) {
    try { const r = await fetch(url); if (r.ok) return true; } catch { /* retry */ }
    await new Promise((r) => setTimeout(r, 400));
  }
  throw new Error("server did not start");
}

let exitCode = 1;
try {
  await waitForServer(`http://localhost:${PORT}/`);
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1100, height: 900 } });
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto(`http://localhost:${PORT}/`, { waitUntil: "networkidle" });

  // welcome screen renders with starter questions
  await page.waitForSelector("textarea", { timeout: 10000 });
  check("app shell + composer rendered", true);
  await page.screenshot({ path: `${OUT}/fe-01-welcome.png` });

  // ask the canned t-test question
  const q = "Walk me through the 4 steps of a one-sample t-test.";
  await page.fill("textarea", q);
  await page.keyboard.press("Enter");

  // wait for the streamed answer to finish (done -> citation chips appear)
  await page.waitForSelector(".katex", { timeout: 20000 });
  await page.waitForFunction(
    () => document.querySelectorAll('button[aria-label^="Citation"], button[aria-label*="citation"]').length > 0,
    { timeout: 20000 },
  ).catch(() => {});
  await page.waitForTimeout(1200); // let streaming settle

  // 1. formulas rendered, none errored
  const katexCount = await page.locator(".katex").count();
  const katexErr = await page.locator(".katex-error").count();
  const displayCount = await page.locator(".katex-display").count();
  check("formulas render as KaTeX", katexCount >= 2, `${katexCount} katex nodes`);
  check("no KaTeX errors", katexErr === 0, `${katexErr} errors`);
  check("display equations centered (.katex-display)", displayCount >= 1, `${displayCount} display blocks`);

  // 2. citation chips present
  const chips = await page.locator('button[aria-label*="itation"]').count();
  check("citation chips rendered", chips >= 1, `${chips} chips`);

  // 3. resource cards are real external links to the course site
  const cardHrefs = await page.locator('a[href^="https://treese41528.github.io"]').evaluateAll(
    (as) => as.map((a) => ({ href: a.getAttribute("href"), target: a.getAttribute("target"), rel: a.getAttribute("rel") })),
  );
  const goodCards = cardHrefs.filter((c) => c.target === "_blank" && (c.rel || "").includes("noopener"));
  check("resource/citation links point to course site w/ safe rel", goodCards.length >= 1,
    `${goodCards.length} safe links`);

  // 4. R code fence rendered as a code block
  const codeBlocks = await page.locator("pre code, pre").count();
  check("code block rendered", codeBlocks >= 1, `${codeBlocks} <pre>`);

  // 5. no uncaught page errors
  check("no uncaught JS errors", errors.length === 0, errors.slice(0, 2).join(" | "));

  await page.screenshot({ path: `${OUT}/fe-02-answer.png`, fullPage: true });

  // 6. click a citation chip -> popover with "Open in course site" link
  try {
    await page.locator('button[aria-label*="itation"]').first().click();
    await page.waitForTimeout(400);
    const popoverLink = await page.locator('a:has-text("Open in course site")').count();
    check("citation popover opens with source link", popoverLink >= 1, `${popoverLink} link`);
    await page.screenshot({ path: `${OUT}/fe-03-citation-popover.png` });
  } catch (e) {
    check("citation popover opens with source link", false, e.message.split("\n")[0]);
  }

  // 7. dark mode toggle doesn't break rendering
  await page.emulateMedia({ colorScheme: "dark" });
  await page.reload({ waitUntil: "networkidle" });
  await page.screenshot({ path: `${OUT}/fe-04-dark.png` });
  check("dark mode renders", true);

  await browser.close();
  const failed = results.filter((r) => !r.ok);
  console.log(`\n${results.length - failed.length}/${results.length} checks passed`);
  exitCode = failed.length === 0 ? 0 : 2;
} catch (e) {
  console.log("HARNESS ERROR:", e.message);
} finally {
  server.kill("SIGTERM");
}
process.exit(exitCode);
