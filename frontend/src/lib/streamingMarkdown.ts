/**
 * Streaming-safe markdown splitting.
 *
 * While tokens stream in, the raw markdown often ends mid-construct: an
 * unclosed ``` fence, an unclosed $$ or $ math span, an unclosed `inline
 * code`, or a partial link ("[see" / "](http…"). Rendering those through the
 * full markdown+KaTeX pipeline causes flicker and partial-math errors.
 *
 * `splitStable(md)` cuts the text into:
 *   - `stable`: everything before the last unclosed construct — safe for the
 *     full pipeline (react-markdown + KaTeX), and
 *   - `tail`: the trailing in-flight fragment — rendered as dimmed plain text
 *     with a blinking caret until it stabilizes.
 */

export interface StableSplit {
  stable: string;
  tail: string;
}

type Mode = "text" | "fence" | "display" | "inline" | "code";

export function splitStable(md: string): StableSplit {
  const n = md.length;
  let mode: Mode = "text";
  let openPos = 0; // where the currently-open construct started
  let linkStart = -1; // position of a '[' whose link is not yet resolved
  let i = 0;

  const atLineStart = (idx: number) => idx === 0 || md[idx - 1] === "\n";

  while (i < n) {
    const ch = md[i];

    if (mode === "fence") {
      if (ch === "`" && md.startsWith("```", i) && atLineStart(i)) {
        mode = "text";
        i += 3;
      } else {
        i++;
      }
      continue;
    }

    if (mode === "display") {
      if (ch === "\\") {
        i += 2; // skip escaped char (covers \$ inside math)
      } else if (ch === "$" && md.startsWith("$$", i)) {
        mode = "text";
        i += 2;
      } else {
        i++; // single $ inside $$ … $$ does NOT toggle inline math
      }
      continue;
    }

    if (mode === "inline") {
      if (ch === "\\") i += 2;
      else if (ch === "$") {
        mode = "text";
        i++;
      } else i++;
      continue;
    }

    if (mode === "code") {
      if (ch === "`") mode = "text";
      i++;
      continue;
    }

    // mode === "text"
    if (ch === "\\") {
      i += 2; // escaped char: \$ \[ \` etc. never open a construct
      continue;
    }
    if (ch === "`") {
      if (md.startsWith("```", i) && atLineStart(i)) {
        mode = "fence";
        openPos = i;
        i += 3;
      } else {
        mode = "code";
        openPos = i;
        i++;
      }
      continue;
    }
    if (ch === "$") {
      if (md.startsWith("$$", i)) {
        mode = "display";
        openPos = i;
        i += 2;
      } else {
        mode = "inline";
        openPos = i;
        i++;
      }
      continue;
    }
    if (ch === "[") {
      if (linkStart === -1) linkStart = i;
      i++;
      continue;
    }
    if (ch === "]") {
      if (linkStart !== -1) {
        if (i + 1 < n && md[i + 1] === "(") {
          // Link URL part: stable only once the ')' arrives.
          const close = md.indexOf(")", i + 2);
          if (close === -1) {
            i = n; // "](http…" still open — whole link is unstable
          } else {
            linkStart = -1;
            i = close + 1;
          }
        } else if (i + 1 === n) {
          // Trailing "]" at the very end: could still become "](url…".
          // Keep it pending — a plain "[1]" stabilizes on the next chunk.
          i++;
        } else {
          linkStart = -1; // plain bracket, e.g. a citation marker "[1]"
          i++;
        }
      } else {
        i++;
      }
      continue;
    }
    i++;
  }

  let cut = n;
  if (mode !== "text") cut = Math.min(cut, openPos);
  if (linkStart !== -1) cut = Math.min(cut, linkStart);
  return { stable: md.slice(0, cut), tail: md.slice(cut) };
}

/**
 * Split stable markdown into blocks on blank lines, WITHOUT splitting inside
 * ``` fences or $$ display math. Each block is rendered as an independently
 * memoized <MarkdownBlock>, so during streaming only the last block re-renders.
 */
/**
 * remark-math only renders `$$…$$` as *display* math (centered, enlarged) when
 * the `$$` sit on their own lines; a single-line `$$ x $$` renders inline. The
 * model emits either style, so normalize a line that is ENTIRELY one `$$…$$`
 * equation into the block form. Inline `$x$` and already-multiline `$$` blocks
 * are untouched.
 */
export function normalizeDisplayMath(md: string): string {
  return md.replace(
    /^([ \t]*)\$\$[ \t]*(\S.*?)[ \t]*\$\$[ \t]*$/gm,
    (_m, indent, inner) => `${indent}$$\n${inner}\n$$`,
  );
}

export function splitBlocks(md: string): string[] {
  if (md === "") return [];
  const lines = md.split("\n");
  const blocks: string[] = [];
  let current: string[] = [];
  let inFence = false;
  let inMath = false;

  const flush = () => {
    if (current.length > 0) {
      const text = current.join("\n");
      if (text.trim() !== "") blocks.push(text);
      current = [];
    }
  };

  for (const line of lines) {
    if (!inMath && /^\s*```/.test(line)) {
      inFence = !inFence;
      current.push(line);
      continue;
    }
    if (!inFence) {
      // Count unescaped $$ occurrences to track display-math state.
      const matches = line.replace(/\\\$/g, "").match(/\$\$/g);
      if (matches && matches.length % 2 === 1) inMath = !inMath;
    }
    if (line.trim() === "" && !inFence && !inMath) {
      flush();
    } else {
      current.push(line);
    }
  }
  flush();
  return blocks;
}
