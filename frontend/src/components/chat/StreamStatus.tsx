import { useChatStore } from "../../stores/chatStore";
import styles from "./StreamStatus.module.css";

/**
 * Animated "thinking" indicator shown in the assistant bubble before the
 * first token: three pulsing dots plus the latest pipeline stage label
 * ("Searching course materials…"). aria-live is OFF here; the Announcer
 * handles screen-reader updates.
 */
export function StreamStatus() {
  const stages = useChatStore((s) => s.stream.stages);
  const phase = useChatStore((s) => s.stream.phase);
  const label =
    stages.length > 0
      ? stages[stages.length - 1].label
      : phase === "connecting"
        ? "Connecting…"
        : "Thinking…";

  return (
    <div className={styles.status} aria-live="off">
      <span className={styles.dots} aria-hidden="true">
        <span />
        <span />
        <span />
      </span>
      <span className={styles.label}>{label}</span>
    </div>
  );
}
