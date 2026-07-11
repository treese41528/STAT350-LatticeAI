import { useCallback, useEffect, useState } from "react";
import clsx from "clsx";
import { useChatStore } from "../../stores/chatStore";
import { TopBar } from "./TopBar";
import { Sidebar } from "./Sidebar";
import { ChatView } from "../chat/ChatView";
import { Announcer } from "../a11y/Announcer";
import styles from "./AppShell.module.css";

const MOBILE_BREAKPOINT = 900;

function isMobile() {
  return typeof window !== "undefined" && window.innerWidth < MOBILE_BREAKPOINT;
}

/**
 * App layout: black topbar, sidebar | main grid. Below 900px the sidebar
 * becomes an overlay drawer with a scrim and body scroll lock.
 *
 * Global keys: Esc stops the stream (dialogs consume Esc first via Radix),
 * Ctrl/Cmd+Shift+O starts a new chat.
 */
export function AppShell() {
  const [sidebarOpen, setSidebarOpen] = useState(() => !isMobile());
  const [mobile, setMobile] = useState(isMobile);

  const stop = useChatStore((s) => s.stop);
  const newChat = useChatStore((s) => s.newChat);

  useEffect(() => {
    const onResize = () => setMobile(isMobile());
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  // Body scroll lock while the mobile drawer is open.
  useEffect(() => {
    const lock = mobile && sidebarOpen;
    document.body.classList.toggle("drawer-open", lock);
    return () => document.body.classList.remove("drawer-open");
  }, [mobile, sidebarOpen]);

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.defaultPrevented) return;
      if (e.key === "Escape") {
        // Radix dialogs/popovers handle their own Esc and stop propagation
        // before this listener sees it, so this only fires "bare".
        if (mobile && sidebarOpen) {
          setSidebarOpen(false);
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
  }, [stop, newChat, mobile, sidebarOpen]);

  const closeDrawer = useCallback(() => {
    if (isMobile()) setSidebarOpen(false);
  }, []);

  return (
    <div className={clsx(styles.shell, !sidebarOpen && styles.sidebarClosed)}>
      <TopBar onToggleSidebar={() => setSidebarOpen((o) => !o)} />

      {mobile && sidebarOpen && (
        <div className={styles.scrim} onClick={() => setSidebarOpen(false)} aria-hidden="true" />
      )}

      <aside
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
