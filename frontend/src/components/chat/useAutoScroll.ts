import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Auto-scroll for the message list.
 *
 * "Pinned" means the user is within 48px of the bottom; while pinned, new
 * content keeps the view glued to the bottom. Scrolling up unpins (shows the
 * JumpToLatest pill); jumping re-pins. The container itself sets
 * overflow-anchor:none so the browser's native anchoring doesn't fight us.
 */

const PIN_THRESHOLD_PX = 48;

export function useAutoScroll(dep: unknown) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const pinnedRef = useRef(true);
  const [pinned, setPinned] = useState(true);

  const handleScroll = useCallback(() => {
    const el = containerRef.current;
    if (!el) return;
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight <= PIN_THRESHOLD_PX;
    pinnedRef.current = nearBottom;
    setPinned(nearBottom);
  }, []);

  const scrollToBottom = useCallback((smooth = false) => {
    const el = containerRef.current;
    if (!el) return;
    el.scrollTo({ top: el.scrollHeight, behavior: smooth ? "smooth" : "auto" });
    pinnedRef.current = true;
    setPinned(true);
  }, []);

  // Keep pinned as content grows (dep changes on every message/token flush).
  useEffect(() => {
    if (pinnedRef.current) {
      const el = containerRef.current;
      if (el) el.scrollTop = el.scrollHeight;
    }
  }, [dep]);

  // Also react to size changes inside the container (images, KaTeX reflow).
  useEffect(() => {
    const el = containerRef.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const inner = el.firstElementChild;
    if (!inner) return;
    const ro = new ResizeObserver(() => {
      if (pinnedRef.current) el.scrollTop = el.scrollHeight;
    });
    ro.observe(inner);
    return () => ro.disconnect();
  }, []);

  return { containerRef, pinned, handleScroll, scrollToBottom };
}
