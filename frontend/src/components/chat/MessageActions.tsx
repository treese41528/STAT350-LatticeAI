import type { Message } from "../../api/types";
import { useAppStore } from "../../stores/appStore";
import { CopyButton } from "../ui/CopyButton";
import { FeedbackButtons } from "../feedback/FeedbackButtons";
import { DigDeeperButton } from "../deeper/DigDeeperButton";
import styles from "./MessageActions.module.css";

/**
 * Action row under a completed assistant message: copy (raw markdown),
 * thumbs up/down, and — when the feature flag is on and this message hasn't
 * already been deepened — the Dig Deeper button.
 */
export function MessageActions({ message }: { message: Message }) {
  const digDeeperEnabled = useAppStore((s) => s.config.features.digDeeper);

  return (
    <div className={styles.actions}>
      <CopyButton text={message.content} label="Copy answer (markdown)" />
      <FeedbackButtons message={message} />
      {digDeeperEnabled && !message.deeper && !message.id.startsWith("local-") ? (
        <DigDeeperButton messageId={message.id} />
      ) : null}
    </div>
  );
}
