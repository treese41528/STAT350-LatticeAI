import { useAppStore } from "../../stores/appStore";
import { useChatStore } from "../../stores/chatStore";
import { IconButton } from "../ui/IconButton";
import { PlusIcon, SidebarIcon } from "../ui/icons";
import { ConnectionStatus } from "./ConnectionStatus";
import { ThemeToggle } from "./ThemeToggle";
import styles from "./TopBar.module.css";

export function TopBar({ onToggleSidebar }: { onToggleSidebar: () => void }) {
  const config = useAppStore((s) => s.config);
  const newChat = useChatStore((s) => s.newChat);

  return (
    <header className={styles.bar}>
      <div className={styles.left}>
        <IconButton
          variant="topbar"
          label="Toggle sidebar"
          onClick={onToggleSidebar}
          className={styles.sidebarBtn}
        >
          <SidebarIcon size={18} />
        </IconButton>
        <div className={styles.wordmark}>
          <span className={styles.course}>{config.courseName}</span>
          <span className={styles.tutor}>Tutor</span>
          {config.term ? <span className={styles.term}>{config.term}</span> : null}
        </div>
      </div>
      <div className={styles.right}>
        <IconButton
          variant="topbar"
          label="New chat (Ctrl+Shift+O)"
          onClick={newChat}
          className={styles.newChatMobile}
        >
          <PlusIcon size={18} />
        </IconButton>
        <ConnectionStatus />
        <ThemeToggle />
      </div>
    </header>
  );
}
