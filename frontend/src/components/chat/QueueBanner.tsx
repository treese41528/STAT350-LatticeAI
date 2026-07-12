import { useChatStore } from "../../stores/chatStore";
import { useAppStore } from "../../stores/appStore";
import { trackEvent } from "../../api/events";
import { Spinner } from "../ui/Spinner";
import { KeyIcon } from "../ui/icons";
import styles from "./QueueBanner.module.css";

export function QueueBanner() {
  const phase = useChatStore((s) => s.stream.phase);
  const position = useChatStore((s) => s.stream.queuePosition);
  const eta = useChatStore((s) => s.stream.queueEtaSeconds);
  const suggestOwnKey = useChatStore((s) => s.stream.suggestOwnKey);

  const byokEnabled = useAppStore((s) => s.config.features.byok === true);
  const ownKeyActive = useAppStore((s) => s.ownKey.status === "active");
  const setSettingsOpen = useAppStore((s) => s.setSettingsOpen);

  if (phase !== "queued" || position == null) return null;

  // Only nudge when the server flagged it, the feature is on, and the student
  // isn't already spending their own quota.
  const showNudge = suggestOwnKey && byokEnabled && !ownKeyActive;

  return (
    <div className={styles.banner}>
      <div className={styles.line}>
        <Spinner size={14} />
        <span>
          You're <strong>#{position}</strong> in line…
          {eta != null && eta > 0 ? ` about ${Math.max(1, Math.round(eta / 5) * 5)}s` : ""}
        </span>
      </div>
      {showNudge && (
        <div className={styles.nudge}>
          <span>The shared class key is busy. Add your own free GenAI Studio key to skip the line.</span>
          <button
            type="button"
            className={styles.nudgeButton}
            onClick={() => {
              trackEvent("own_key_suggested", { context: "queue", position });
              setSettingsOpen(true);
            }}
          >
            <KeyIcon size={14} />
            Add your key
          </button>
        </div>
      )}
    </div>
  );
}
