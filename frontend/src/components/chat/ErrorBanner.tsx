import { useChatStore } from "../../stores/chatStore";
import { Button } from "../ui/Button";
import { AlertIcon, RetryIcon, XIcon } from "../ui/icons";
import { IconButton } from "../ui/IconButton";
import styles from "./ErrorBanner.module.css";

export function ErrorBanner() {
  const error = useChatStore((s) => s.error);
  const retry = useChatStore((s) => s.retry);
  const clearError = useChatStore((s) => s.clearError);

  if (!error) return null;

  return (
    <div className={styles.banner} role="alert">
      <AlertIcon size={17} className={styles.icon} />
      <span className={styles.message}>{error.message}</span>
      <div className={styles.actions}>
        {error.retryable && (
          <Button size="sm" variant="outline" onClick={retry} className={styles.retry}>
            <RetryIcon size={13} />
            Retry
          </Button>
        )}
        <IconButton size="sm" label="Dismiss" onClick={clearError}>
          <XIcon size={15} />
        </IconButton>
      </div>
    </div>
  );
}
