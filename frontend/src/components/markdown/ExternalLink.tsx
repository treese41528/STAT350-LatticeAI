import type { AnchorHTMLAttributes, ReactNode } from "react";

/**
 * Link renderer for markdown content. http(s) links open in a new tab with
 * rel="noopener noreferrer". Anything else (javascript:, data:, relative
 * paths from a confused model, …) renders as plain text — never a live link.
 */
export function ExternalLink({
  href,
  children,
  ...rest
}: AnchorHTMLAttributes<HTMLAnchorElement> & { children?: ReactNode; node?: unknown }) {
  void rest;
  if (!href || !/^https?:\/\//i.test(href)) {
    return <span>{children}</span>;
  }
  return (
    <a href={href} target="_blank" rel="noopener noreferrer">
      {children}
    </a>
  );
}
