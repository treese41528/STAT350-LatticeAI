import { memo } from "react";
import type { Message } from "../../api/types";
import styles from "./UserMessage.module.css";

export const UserMessage = memo(function UserMessage({ message }: { message: Message }) {
  return (
    <div className={styles.row}>
      <div className={styles.bubble}>{message.content}</div>
    </div>
  );
});
