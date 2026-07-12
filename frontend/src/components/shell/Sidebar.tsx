import { useState } from "react";
import { useChatStore } from "../../stores/chatStore";
import { useAppStore } from "../../stores/appStore";
import { Button } from "../ui/Button";
import { PlusIcon } from "../ui/icons";
import { ConversationList } from "./ConversationList";
import { SidebarFooter } from "./SidebarFooter";
import { SettingsDialog } from "../settings/SettingsDialog";
import { ModalityDialog } from "../settings/ModalityDialog";
import styles from "./Sidebar.module.css";

export function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const newChat = useChatStore((s) => s.newChat);
  // Settings open-state is shared (appStore) so the queue "add your own key"
  // nudge can open it too — not only the footer button below.
  const settingsOpen = useAppStore((s) => s.settingsOpen);
  const setSettingsOpen = useAppStore((s) => s.setSettingsOpen);
  const [modalityOpen, setModalityOpen] = useState(false);

  return (
    <div className={styles.sidebar}>
      <div className={styles.header}>
        <Button
          variant="outline"
          className={styles.newChat}
          onClick={() => {
            newChat();
            onNavigate?.();
          }}
        >
          <PlusIcon size={16} />
          New chat
        </Button>
      </div>
      <ConversationList onNavigate={onNavigate} />
      <SidebarFooter onOpenSettings={() => setSettingsOpen(true)} />
      <SettingsDialog
        open={settingsOpen}
        onOpenChange={setSettingsOpen}
        onOpenModality={() => setModalityOpen(true)}
      />
      <ModalityDialog open={modalityOpen} onOpenChange={setModalityOpen} />
    </div>
  );
}
