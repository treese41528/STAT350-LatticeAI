import { createContext, memo, useMemo } from "react";
import type { Citation } from "../../api/types";
import { splitBlocks, splitStable } from "../../lib/streamingMarkdown";
import { MarkdownBlock } from "./MarkdownBlock";
import styles from "./MessageMarkdown.module.css";

/**
 * SECURITY INVARIANT — NO rehype-raw, ever.
 *
 * react-markdown drops raw HTML in the source by default; that is exactly the
 * behavior we depend on. Model output and retrieved snippets must never be
 * parsed as HTML. Do NOT add rehype-raw (or any HTML-passthrough plugin) to
 * this pipeline. KaTeX runs with trust:false, throwOnError:false,
 * strict:"ignore" (configured in MarkdownBlock) so \href, \htmlClass and
 * friends stay disabled too.
 *
 * Rendering strategy:
 *  - While streaming, `splitStable` separates fully-formed markdown from the
 *    in-flight tail; the tail renders as dimmed plain text with a caret so
 *    KaTeX never sees partial math and fences never flicker.
 *  - Stable content is split into blocks on blank lines (fence/math aware).
 *    Each block is a memoized <MarkdownBlock>, so during streaming only the
 *    last block ever re-renders.
 *  - `>>> BEYOND STAT 350 SCOPE ... <<<` lines become a gold-tinted banner
 *    (purely cosmetic transform, the text itself is preserved).
 */

export const CitationsContext = createContext<Citation[]>([]);

const BEYOND_RE = />{3}\s*(BEYOND STAT ?350 SCOPE[^<]*?)<{3}/;

export interface MessageMarkdownProps {
  content: string;
  citations: Citation[];
  streaming?: boolean;
}

export const MessageMarkdown = memo(function MessageMarkdown({
  content,
  citations,
  streaming = false,
}: MessageMarkdownProps) {
  const { stable, tail } = useMemo(
    () => (streaming ? splitStable(content) : { stable: content, tail: "" }),
    [content, streaming],
  );

  const blocks = useMemo(() => splitBlocks(stable), [stable]);

  return (
    <CitationsContext.Provider value={citations}>
      <div className={styles.markdown}>
        {blocks.map((block, i) => {
          const beyond = block.match(BEYOND_RE);
          if (beyond) {
            return (
              <div key={i} className={styles.beyondBanner} role="note">
                <span className={styles.beyondTag}>Beyond STAT 350</span>
                <span>{beyond[1].trim()}</span>
              </div>
            );
          }
          return <MarkdownBlock key={i} text={block} citationCount={citations.length} />;
        })}
        {tail !== "" && (
          <span className={styles.tail} aria-hidden="true">
            {tail}
            <span className={styles.caret} />
          </span>
        )}
        {streaming && tail === "" && content !== "" && (
          <span className={styles.caret} aria-hidden="true" />
        )}
      </div>
    </CitationsContext.Provider>
  );
});
