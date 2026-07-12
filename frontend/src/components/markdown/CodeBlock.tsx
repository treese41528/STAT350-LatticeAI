import { isValidElement, useEffect, useState, type ReactNode } from "react";
import { highlightCode } from "../../lib/shiki";
import { CopyButton } from "../ui/CopyButton";
import styles from "./CodeBlock.module.css";

/**
 * Fenced code renderer (mapped from `pre` in the markdown pipeline).
 *
 * Shiki is loaded lazily on the FIRST code fence only (fine-grained core +
 * JS regex engine + the `r` grammar + github-light/dark themes). Other
 * languages render as a plain <pre> — no grammars are shipped for them.
 *
 * The dangerouslySetInnerHTML below is safe: the HTML comes exclusively from
 * Shiki, which escapes all code content; no model/user text is interpolated.
 */

interface ExtractedCode {
  code: string;
  lang: string;
}

function extractCode(children: ReactNode): ExtractedCode {
  if (isValidElement(children)) {
    const props = children.props as { className?: string; children?: ReactNode };
    const lang = /language-([\w-]+)/.exec(props.className ?? "")?.[1] ?? "";
    const raw = props.children;
    const code = typeof raw === "string" ? raw : Array.isArray(raw) ? raw.join("") : String(raw ?? "");
    return { code: code.replace(/\n$/, ""), lang };
  }
  return { code: typeof children === "string" ? children : "", lang: "" };
}

export function CodeBlock({ children }: { children?: ReactNode }) {
  const { code, lang } = extractCode(children);
  const [html, setHtml] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    setHtml(null);
    if (lang.toLowerCase() === "r" && code !== "") {
      highlightCode(code, lang)
        .then((result) => {
          if (alive && result) setHtml(result);
        })
        .catch(() => {
          /* fall back to plain rendering */
        });
    }
    return () => {
      alive = false;
    };
  }, [code, lang]);

  return (
    <div className={styles.wrapper}>
      <div className={styles.header}>
        <span className={styles.lang}>{lang || "code"}</span>
        <CopyButton text={code} label="Copy code" />
      </div>
      {html ? (
        // Safe: Shiki output only (see module docblock).
        <div className={styles.shiki} dangerouslySetInnerHTML={{ __html: html }} />
      ) : (
        <pre className={styles.plain}>
          <code>{code}</code>
        </pre>
      )}
    </div>
  );
}
