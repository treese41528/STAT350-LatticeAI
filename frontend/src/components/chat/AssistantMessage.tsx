import { memo } from "react";
import type { Message } from "../../api/types";
import { useChatStore } from "../../stores/chatStore";
import { MessageMarkdown } from "../markdown/MessageMarkdown";
import { SourcesPanel } from "../sources/SourcesPanel";
import { ResourceCardRow } from "../sources/ResourceCardRow";
import { RefusalCard } from "./RefusalCard";
import { StreamStatus } from "./StreamStatus";
import { MessageActions } from "./MessageActions";
import { DeeperProgress } from "../deeper/DeeperProgress";
import styles from "./AssistantMessage.module.css";

/**
 * One assistant turn. Memoized — during streaming the store only replaces
 * the message object being streamed, so all other bubbles skip re-render.
 * The streaming region is aria-live=off (Announcer handles SR updates) and
 * aria-busy while tokens are arriving.
 */
export const AssistantMessage = memo(function AssistantMessage({ message }: { message: Message }) {
  const isStreamTarget = useChatStore(
    (s) => s.stream.messageId === message.id && s.stream.phase !== "idle",
  );

  const thinking = message.status === "queued" && isStreamTarget;
  const streaming = message.status === "streaming";

  return (
    <div className={styles.row}>
      <div className={styles.avatar} aria-hidden="true">
        Σ
      </div>
      <div className={styles.body} aria-live="off" aria-busy={thinking || streaming}>
        <div className={styles.name}>STAT 350 Tutor</div>

        {thinking && <StreamStatus />}

        {message.content !== "" && (
          <MessageMarkdown
            content={message.content}
            citations={message.citations}
            streaming={streaming}
          />
        )}

        {message.status === "refused" && message.refusal && (
          <RefusalCard refusal={message.refusal} />
        )}

        {message.status === "error" && message.content === "" && (
          <p className={styles.errorNote}>This answer didn't make it. Use Retry below.</p>
        )}

        {message.resources.length > 0 && !thinking && (
          <ResourceCardRow resources={message.resources} />
        )}

        {message.citations.length > 0 && !thinking && (
          <SourcesPanel citations={message.citations} />
        )}

        {message.deeper && <DeeperProgress deeper={message.deeper} />}

        {(message.status === "complete" || message.status === "refused") &&
          message.content !== "" && <MessageActions message={message} />}
      </div>
    </div>
  );
});
