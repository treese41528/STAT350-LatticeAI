import { memo, useMemo } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import rehypeCitations from "../../lib/rehypeCitations";
import { normalizeDisplayMath } from "../../lib/streamingMarkdown";
import { CitationMarker } from "./CitationMarker";
import { CodeBlock } from "./CodeBlock";
import { ExternalLink } from "./ExternalLink";
import type { PluggableList } from "unified";

/**
 * One markdown block (paragraph / fence / display equation / table…).
 * Memoized on (text, citationCount): during streaming only the final block's
 * text changes, so earlier blocks — including expensive KaTeX renders — are
 * never re-rendered.
 *
 * NOTE: no rehype-raw here (see MessageMarkdown for the invariant). Raw HTML
 * in the markdown source is intentionally dropped by react-markdown.
 */

const REMARK_PLUGINS: PluggableList = [remarkGfm, remarkMath];

const KATEX_OPTIONS = {
  trust: false, // never honor \href, \htmlClass, \includegraphics, …
  throwOnError: false, // render bad TeX as source-in-red, not an exception
  strict: "ignore" as const,
};

/* Custom components:
   - "cite-n" elements (from rehypeCitations) -> interactive CitationMarker
   - links open in a new tab; non-http(s) hrefs render as plain text
   - fenced code -> CodeBlock (lazy Shiki highlight for R) */
const COMPONENTS = {
  a: ExternalLink,
  pre: CodeBlock,
  "cite-n": CitationMarker,
} as Components;

export const MarkdownBlock = memo(function MarkdownBlock({
  text,
  citationCount,
}: {
  text: string;
  citationCount: number;
}) {
  const rehypePlugins: PluggableList = useMemo(
    () => [
      [rehypeKatex, KATEX_OPTIONS],
      [rehypeCitations, { max: citationCount }],
    ],
    [citationCount],
  );

  const normalized = useMemo(() => normalizeDisplayMath(text), [text]);

  return (
    <ReactMarkdown
      remarkPlugins={REMARK_PLUGINS}
      rehypePlugins={rehypePlugins}
      components={COMPONENTS}
    >
      {normalized}
    </ReactMarkdown>
  );
});
