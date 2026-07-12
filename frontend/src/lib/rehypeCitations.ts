import type { Element, ElementContent, Root, RootContent, Text } from "hast";

/**
 * Rehype plugin: turn inline "[n]" markers in prose into <cite-n data-n="n">
 * elements, which MessageMarkdown maps to the interactive <CitationMarker>.
 *
 * Rules:
 *  - only for 1 <= n <= options.max (i.e. a matching citation exists);
 *  - never inside code/pre/a/script/style;
 *  - never inside KaTeX output (any element whose class mentions katex/math),
 *    so things like the interval "[1, 2]" in rendered math are left alone.
 */

export interface RehypeCitationsOptions {
  max: number;
}

const SKIP_TAGS = new Set(["code", "pre", "a", "script", "style", "cite-n"]);
const MARKER_RE = /\[(\d{1,2})\]/g;

function isSkipped(el: Element): boolean {
  if (SKIP_TAGS.has(el.tagName)) return true;
  const cls = el.properties?.className;
  const classes = Array.isArray(cls) ? cls.join(" ") : typeof cls === "string" ? cls : "";
  return /katex|math/i.test(classes);
}

function transformText(node: Text, max: number): ElementContent[] | null {
  const value = node.value;
  MARKER_RE.lastIndex = 0;
  if (!MARKER_RE.test(value)) return null;
  MARKER_RE.lastIndex = 0;

  const out: ElementContent[] = [];
  let last = 0;
  let match: RegExpExecArray | null;
  let replaced = false;
  while ((match = MARKER_RE.exec(value)) !== null) {
    const n = Number(match[1]);
    if (n < 1 || n > max) continue; // no such citation — leave the text as-is
    if (match.index > last) out.push({ type: "text", value: value.slice(last, match.index) });
    out.push({
      type: "element",
      tagName: "cite-n",
      properties: { dataN: String(n) },
      children: [],
    });
    last = match.index + match[0].length;
    replaced = true;
  }
  if (!replaced) return null;
  if (last < value.length) out.push({ type: "text", value: value.slice(last) });
  return out;
}

function walk(node: Root | Element, max: number): void {
  const children = node.children as (RootContent | ElementContent)[];
  for (let i = 0; i < children.length; i++) {
    const child = children[i];
    if (child.type === "element") {
      if (!isSkipped(child)) walk(child, max);
    } else if (child.type === "text") {
      const parts = transformText(child, max);
      if (parts) {
        children.splice(i, 1, ...parts);
        i += parts.length - 1;
      }
    }
  }
}

export default function rehypeCitations(options: RehypeCitationsOptions) {
  const max = options?.max ?? 0;
  return (tree: Root) => {
    if (max > 0) walk(tree, max);
  };
}
