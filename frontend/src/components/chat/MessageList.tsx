import { useChatStore } from "../../stores/chatStore";
import { UserMessage } from "./UserMessage";
import { AssistantMessage } from "./AssistantMessage";
import { useAutoScroll } from "./useAutoScroll";
import { ArrowDownIcon } from "../ui/icons";
import styles from "./MessageList.module.css";

export function MessageList({ conversationId }: { conversationId: string }) {
  const messages = useChatStore((s) => s.messages[conversationId]) ?? [];
  const { containerRef, pinned, handleScroll, scrollToBottom } = useAutoScroll(messages);

  return (
    <div className={styles.wrapper}>
      <div
        ref={containerRef}
        className={styles.scroller}
        onScroll={handleScroll}
        tabIndex={0}
        aria-label="Conversation messages"
      >
        <div className={styles.inner}>
          {messages.map((m) =>
            m.role === "user" ? (
              <UserMessage key={m.id} message={m} />
            ) : (
              <AssistantMessage key={m.id} message={m} />
            ),
          )}
        </div>
      </div>
      {!pinned && (
        <button
          type="button"
          className={styles.jumpPill}
          onClick={() => scrollToBottom(true)}
        >
          <ArrowDownIcon size={14} />
          Jump to latest
        </button>
      )}
    </div>
  );
}
