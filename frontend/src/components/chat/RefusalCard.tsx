import type { Message } from "../../api/types";
import { AlertIcon, SearchOffIcon, ShieldIcon } from "../ui/icons";
import styles from "./RefusalCard.module.css";

const REASON_META: Record<string, { title: string; Icon: typeof AlertIcon }> = {
  integrity: { title: "Academic integrity", Icon: ShieldIcon },
  weak_retrieval: { title: "Not enough course material found", Icon: SearchOffIcon },
  out_of_scope: { title: "Outside STAT 350", Icon: AlertIcon },
};

export function RefusalCard({ refusal }: { refusal: NonNullable<Message["refusal"]> }) {
  const meta = REASON_META[refusal.reason] ?? {
    title: "Can't help with that one",
    Icon: AlertIcon,
  };
  const Icon = meta.Icon;
  return (
    <div className={styles.card} role="note">
      <span className={styles.icon}>
        <Icon size={18} />
      </span>
      <div>
        <div className={styles.title}>{meta.title}</div>
        <p className={styles.message}>{refusal.message}</p>
      </div>
    </div>
  );
}
