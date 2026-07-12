import clsx from "clsx";
import type { Message } from "../../api/types";
import { CheckIcon } from "../ui/icons";
import { Spinner } from "../ui/Spinner";
import styles from "./DeeperProgress.module.css";

/** Vertical stage timeline for a "dig deeper" run attached to a message. */
export function DeeperProgress({ deeper }: { deeper: NonNullable<Message["deeper"]> }) {
  return (
    <div className={styles.wrapper} aria-live="off">
      <div className={styles.heading}>
        {deeper.status === "running" && (
          <>
            <Spinner size={14} /> Digging deeper…
          </>
        )}
        {deeper.status === "done" && (
          <>
            <CheckIcon size={14} className={styles.doneIcon} /> Deeper answer below
          </>
        )}
        {deeper.status === "error" && "Deeper pass failed"}
      </div>
      {deeper.stages.length > 0 && (
        <ol className={styles.timeline}>
          {deeper.stages.map((stage, i) => {
            const active = !stage.done && deeper.status === "running";
            return (
              <li
                key={`${stage.stage}-${i}`}
                className={clsx(styles.stage, stage.done && styles.stageDone, active && styles.stageActive)}
              >
                <span className={styles.dot}>
                  {stage.done ? <CheckIcon size={10} /> : null}
                </span>
                <span className={styles.label}>{stage.label}</span>
              </li>
            );
          })}
        </ol>
      )}
    </div>
  );
}
