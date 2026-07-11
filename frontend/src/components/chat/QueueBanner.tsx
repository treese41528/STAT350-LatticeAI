import { useChatStore } from "../../stores/chatStore";
import { Spinner } from "../ui/Spinner";
import styles from "./QueueBanner.module.css";

export function QueueBanner() {
  const phase = useChatStore((s) => s.stream.phase);
  const position = useChatStore((s) => s.stream.queuePosition);
  const eta = useChatStore((s) => s.stream.queueEtaSeconds);

  if (phase !== "queued" || position == null) return null;

  return (
    <div className={styles.banner}>
      <Spinner size={14} />
      <span>
        You're <strong>#{position}</strong> in line…
        {eta != null && eta > 0 ? ` about ${Math.max(1, Math.round(eta / 5) * 5)}s` : ""}
      </span>
    </div>
  );
}
