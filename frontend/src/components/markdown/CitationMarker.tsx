import { useContext } from "react";
import { Popover } from "radix-ui";
import clsx from "clsx";
import { CitationsContext } from "./MessageMarkdown";
import { Badge } from "../ui/Badge";
import { ExternalIcon } from "../ui/icons";
import styles from "./CitationMarker.module.css";

/**
 * Inline [n] citation chip. Rendered for <cite-n data-n="…"> elements emitted
 * by rehypeCitations. The popover shows the source badge, title, a PLAIN-TEXT
 * snippet ({snippet} interpolation only — never innerHTML) and a qualitative
 * match-strength meter (no raw similarity numbers for students).
 */

type Strength = "strong" | "moderate" | "weak";

function strengthOf(similarity: number): Strength {
  if (similarity >= 0.75) return "strong";
  if (similarity >= 0.5) return "moderate";
  return "weak";
}

const STRENGTH_LABEL: Record<Strength, string> = {
  strong: "Strong match",
  moderate: "Moderate match",
  weak: "Weak match",
};

export function CitationMarker(props: Record<string, unknown>) {
  const citations = useContext(CitationsContext);
  const n = Number(props["data-n"]);
  const citation = citations.find((c) => c.n === n) ?? citations[n - 1];

  if (!citation) {
    return <sup className={styles.plain}>[{n}]</sup>;
  }

  const strength = strengthOf(citation.similarity);

  return (
    <Popover.Root>
      <Popover.Trigger asChild>
        <button
          type="button"
          className={styles.chip}
          aria-label={`Citation ${n}: ${citation.title}`}
        >
          {n}
        </button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content className={clsx(styles.content, "citationSheet")} sideOffset={6} collisionPadding={12}>
          <div className={styles.headerRow}>
            <Badge tone={citation.source === "webbook" ? "gold" : "steel"}>
              {citation.source === "webbook" ? "Webbook" : "Transcript"}
            </Badge>
            <div
              className={clsx(styles.meter, styles[strength])}
              role="img"
              aria-label={STRENGTH_LABEL[strength]}
              title={STRENGTH_LABEL[strength]}
            >
              <span />
              <span />
              <span />
            </div>
          </div>
          <div className={styles.title}>{citation.title}</div>
          {/* Plain text interpolation — retrieved snippets are untrusted. */}
          <p className={styles.snippet}>{citation.snippet}</p>
          {citation.url && /^https?:\/\//i.test(citation.url) ? (
            <a
              className={styles.openLink}
              href={citation.url}
              target="_blank"
              rel="noopener noreferrer"
            >
              Open in course site <ExternalIcon size={13} />
            </a>
          ) : null}
          <Popover.Arrow className={styles.arrow} />
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}
