import { useCallback, useEffect, useRef, useState } from "react";
import clsx from "clsx";
import { useChatStore } from "../../stores/chatStore";
import { TopBar } from "./TopBar";
import { Sidebar } from "./Sidebar";
import { ChatView } from "../chat/ChatView";
import { Announcer } from "../a11y/Announcer";
import styles from "./AppShell.module.css";

const MOBILE_BREAKPOINT = 900;
const COLLAPSE_KEY = "stat350.sidebarCollapsed";

function isMobile() {
  return typeof window !== "undefined" && window.innerWidth < MOBILE_BREAKPOINT;
}

function loadCollapsed(): boolean {
  try {
    return localStorage.getItem(COLLAPSE_KEY) === "1";
  } catch {
    return false;
  }
}

/**
 * App layout: black topbar, sidebar | main grid.
 *
 * The sidebar has TWO independent states so that crossing the 900px breakpoint
 * never carries the wrong one over (the old single flag made the overlay drawer
 * pop open over the chat when you shrank the window, and hid the desktop rail
 * when you grew it back):
 *   - desktopCollapsed — the persisted rail preference on wide screens
 *   - drawerOpen       — the ephemeral overlay on phones/tablets; always starts
 *                        closed and re-closes whenever we enter mobile
 * What's actually shown is derived: mobile ? drawerOpen : !desktopCollapsed.
 *
 * Global keys: Esc closes the mobile drawer, else stops the stream;
 * Ctrl/Cmd+Shift+O starts a new chat.
 */
export function AppShell() {
  const [mobile, setMobile] = useState(isMobile);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [desktopCollapsed, setDesktopCollapsed] = useState(loadCollapsed);
  const mobileRef = useRef(mobile);

  const stop = useChatStore((s) => s.stop);
  const newChat = useChatStore((s) => s.newChat);

  const sidebarOpen = mobile ? drawerOpen : !desktopCollapsed;

  // Only react when the viewport actually crosses the breakpoint (not on every
  // resize pixel). Entering mobile force-closes the overlay so shrinking the
  // window can't pop the menu open over the chat.
  useEffect(() => {
    const onResize = () => {
      const m = isMobile();
      if (m === mobileRef.current) return;
      mobileRef.current = m;
      setMobile(m);
      if (m) setDrawerOpen(false);
    };
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  // Body scroll lock only while the mobile drawer is actually open.
  useEffect(() => {
    const lock = mobile && drawerOpen;
    document.body.classList.toggle("drawer-open", lock);
    return () => document.body.classList.remove("drawer-open");
  }, [mobile, drawerOpen]);

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.defaultPrevented) return;
      if (e.key === "Escape") {
        // Radix dialogs/popovers handle their own Esc and stop propagation
        // before this listener sees it, so this only fires "bare".
        if (mobile && drawerOpen) {
          setDrawerOpen(false);
        } else {
          stop();
        }
        return;
      }
      if ((e.ctrlKey || e.metaKey) && e.shiftKey && (e.key === "O" || e.key === "o")) {
        e.preventDefault();
        newChat();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [stop, newChat, mobile, drawerOpen]);

  // The one toggle button drives whichever state is live for this viewport.
  const toggleSidebar = useCallback(() => {
    if (isMobile()) {
      setDrawerOpen((o) => !o);
    } else {
      setDesktopCollapsed((c) => {
        const next = !c;
        try {
          localStorage.setItem(COLLAPSE_KEY, next ? "1" : "0");
        } catch {
          /* localStorage may be unavailable (private mode) — non-fatal */
        }
        return next;
      });
    }
  }, []);

  const closeDrawer = useCallback(() => {
    if (isMobile()) setDrawerOpen(false);
  }, []);

  return (
    <div className={clsx(styles.shell, !sidebarOpen && styles.sidebarClosed)}>
      <TopBar onToggleSidebar={toggleSidebar} sidebarOpen={sidebarOpen} />

      {mobile && drawerOpen && (
        <div className={styles.scrim} onClick={() => setDrawerOpen(false)} aria-hidden="true" />
      )}

      <aside
        id="app-sidebar"
        className={clsx(styles.sidebar, mobile && styles.sidebarDrawer, {
          [styles.sidebarHidden]: !sidebarOpen,
        })}
        aria-label="Conversation history"
        aria-hidden={!sidebarOpen}
        {...(!sidebarOpen ? { inert: true } : {})}
      >
        <Sidebar onNavigate={closeDrawer} />
      </aside>

      <main className={styles.main}>
        <ChatView />
      </main>

      <Announcer />
    </div>
  );
}
