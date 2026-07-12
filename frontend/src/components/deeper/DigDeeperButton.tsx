import { useChatStore } from "../../stores/chatStore";
import { Button } from "../ui/Button";
import { SparkIcon } from "../ui/icons";
import styles from "./DigDeeperButton.module.css";

export function DigDeeperButton({ messageId }: { messageId: string }) {
  const digDeeper = useChatStore((s) => s.digDeeper);
  const busy = useChatStore((s) => s.stream.phase !== "idle");

  return (
    <Button
      variant="outline"
      size="sm"
      className={styles.button}
      disabled={busy}
      onClick={() => void digDeeper(messageId)}
    >
      <SparkIcon size={14} />
      Dig deeper — slower, more thorough
    </Button>
  );
}
