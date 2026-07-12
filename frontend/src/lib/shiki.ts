import type { HighlighterCore } from "shiki/core";

/**
 * Lazy, fine-grained Shiki: nothing is downloaded until the first R code
 * fence appears. Only the JS regex engine, the `r` grammar and the two GitHub
 * themes are loaded — no WASM, no full language registry.
 */

let highlighterPromise: Promise<HighlighterCore> | null = null;

function loadHighlighter(): Promise<HighlighterCore> {
  highlighterPromise ??= (async () => {
    const [{ createHighlighterCore }, { createJavaScriptRegexEngine }, r, light, dark] =
      await Promise.all([
        import("shiki/core"),
        import("shiki/engine/javascript"),
        import("@shikijs/langs/r"),
        import("@shikijs/themes/github-light"),
        import("@shikijs/themes/github-dark"),
      ]);
    return createHighlighterCore({
      langs: [r.default],
      themes: [light.default, dark.default],
      engine: createJavaScriptRegexEngine(),
    });
  })();
  return highlighterPromise;
}

/**
 * Highlight R source to HTML with dual themes (CSS variables switch them; see
 * markdown.css). Shiki escapes all code content, so the output is safe to
 * inject. Returns null for languages we don't ship a grammar for.
 */
export async function highlightCode(code: string, lang: string): Promise<string | null> {
  if (lang.toLowerCase() !== "r") return null;
  const highlighter = await loadHighlighter();
  return highlighter.codeToHtml(code, {
    lang: "r",
    themes: { light: "github-light", dark: "github-dark" },
    defaultColor: "light",
  });
}
