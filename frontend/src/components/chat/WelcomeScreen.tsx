import { useAppStore } from "../../stores/appStore";
import { useChatStore } from "../../stores/chatStore";
import styles from "./WelcomeScreen.module.css";

/** Empty-state hero: wordmark, welcome copy, starter question cards. */
export function WelcomeScreen() {
  const config = useAppStore((s) => s.config);
  const send = useChatStore((s) => s.send);
  const busy = useChatStore((s) => s.stream.phase !== "idle");

  return (
    <div className={styles.wrapper}>
      <div className={styles.hero}>
        <div className={styles.mark} aria-hidden="true">
          Σ
        </div>
        <h1 className={styles.title}>
          {config.courseName} Tutor
          {config.term ? <span className={styles.term}> · {config.term}</span> : null}
        </h1>
        <p className={styles.welcome}>{config.welcome}</p>
      </div>
      {config.starterQuestions.length > 0 && (
        <div className={styles.cards}>
          {config.starterQuestions.map((q) => (
            <button
              key={q}
              type="button"
              className={styles.card}
              disabled={busy}
              onClick={() => void send(q)}
            >
              {q}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
