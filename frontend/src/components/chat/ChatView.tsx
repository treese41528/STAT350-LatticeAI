import { useChatStore } from "../../stores/chatStore";
import { MessageList } from "./MessageList";
import { WelcomeScreen } from "./WelcomeScreen";
import { QueueBanner } from "./QueueBanner";
import { ErrorBanner } from "./ErrorBanner";
import { Composer } from "./Composer";
import styles from "./ChatView.module.css";

export function ChatView() {
  const activeId = useChatStore((s) => s.activeId);
  const hasMessages = useChatStore(
    (s) => s.activeId != null && (s.messages[s.activeId]?.length ?? 0) > 0,
  );

  return (
    <div className={styles.view}>
      {activeId && hasMessages ? <MessageList conversationId={activeId} /> : <WelcomeScreen />}
      <div className={styles.banners}>
        <QueueBanner />
        <ErrorBanner />
      </div>
      <Composer />
    </div>
  );
}
