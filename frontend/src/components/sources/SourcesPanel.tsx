import { useState } from "react";
import clsx from "clsx";
import type { Citation } from "../../api/types";
import { Badge } from "../ui/Badge";
import { ChevronDownIcon, ExternalIcon } from "../ui/icons";
import styles from "./SourcesPanel.module.css";

/**
 * Collapsed "Sources (n)" disclosure under an answer. Snippets render as
 * plain text — retrieval output is untrusted.
 */
export function SourcesPanel({ citations }: { citations: Citation[] }) {
  const [open, setOpen] = useState(false);
  if (citations.length === 0) return null;

  return (
    <div className={styles.panel}>
      <button
        type="button"
        className={styles.toggle}
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
      >
        <ChevronDownIcon size={14} className={clsx(styles.chevron, open && styles.chevronOpen)} />
        Sources ({citations.length})
      </button>
      {open && (
        <ol className={styles.list}>
          {citations.map((c) => (
            <li key={c.n} className={styles.item}>
              <div className={styles.itemHeader}>
                <span className={styles.n}>[{c.n}]</span>
                <Badge tone={c.source === "webbook" ? "gold" : "steel"}>
                  {c.source === "webbook" ? "Webbook" : "Transcript"}
                </Badge>
                <span className={styles.title}>{c.title}</span>
              </div>
              <p className={styles.snippet}>{c.snippet}</p>
              {c.url && /^https?:\/\//i.test(c.url) ? (
                <a className={styles.link} href={c.url} target="_blank" rel="noopener noreferrer">
                  Open in course site <ExternalIcon size={12} />
                </a>
              ) : null}
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
