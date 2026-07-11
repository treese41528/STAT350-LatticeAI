import { useCallback, useEffect, useRef, useState } from "react";
import clsx from "clsx";
import { useChatStore } from "../../stores/chatStore";
import { useAppStore } from "../../stores/appStore";
import { SendIcon, StopIcon } from "../ui/icons";
import styles from "./Composer.module.css";

const MAX_TEXTAREA_PX = 200;

/**
 * Message composer: auto-resizing textarea (16px font so iOS doesn't zoom),
 * Enter to send / Shift+Enter for newline, Send<->Stop toggle while
 * streaming, and a character counter that appears near the limit.
 */
export function Composer() {
  const [value, setValue] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);

  const send = useChatStore((s) => s.send);
  const stop = useChatStore((s) => s.stop);
  const phase = useChatStore((s) => s.stream.phase);
  const maxChars = useAppStore((s) => s.config.maxMessageChars);

  const busy = phase !== "idle";
  const overLimit = value.length > maxChars;
  const nearLimit = value.length >= maxChars * 0.85;

  const resize = useCallback(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, MAX_TEXTAREA_PX)}px`;
  }, []);

  useEffect(resize, [value, resize]);

  const doSend = () => {
    const text = value.trim();
    if (text === "" || busy || overLimit) return;
    setValue("");
    void send(text);
    // Return focus for rapid follow-ups.
    requestAnimationFrame(() => textareaRef.current?.focus());
  };

  return (
    <div className={styles.container}>
      <div className={styles.inner}>
        <div className={clsx(styles.inputWrap, overLimit && styles.inputOver)}>
          <textarea
            ref={textareaRef}
            className={styles.textarea}
            rows={1}
            value={value}
            placeholder="Ask about STAT 350 — concepts, homework strategy, R code…"
            aria-label="Message the STAT 350 tutor"
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                doSend();
              }
            }}
          />
          {nearLimit && (
            <span
              className={clsx(styles.counter, overLimit && styles.counterOver)}
              aria-live="polite"
            >
              {value.length.toLocaleString()} / {maxChars.toLocaleString()}
            </span>
          )}
        </div>
        {busy ? (
          <button
            type="button"
            className={clsx(styles.actionBtn, styles.stopBtn)}
            onClick={stop}
            aria-label="Stop generating"
            title="Stop generating (Esc)"
          >
            <StopIcon size={18} />
          </button>
        ) : (
          <button
            type="button"
            className={styles.actionBtn}
            onClick={doSend}
            disabled={value.trim() === "" || overLimit}
            aria-label="Send message"
            title="Send (Enter)"
          >
            <SendIcon size={18} />
          </button>
        )}
      </div>
      <p className={styles.hint}>
        The tutor guides you Socratically — expect questions back. Check important results against
        the course website.
      </p>
    </div>
  );
}
