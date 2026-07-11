import { useState } from "react";
import { useAppStore, MODALITY_LABELS } from "../../stores/appStore";
import { GradIcon } from "../ui/icons";
import { ModalityDialog } from "./ModalityDialog";
import styles from "./ModalityBadge.module.css";

/** Sidebar footer chip showing the student's section; click to change. */
export function ModalityBadge() {
  const modality = useAppStore((s) => s.modality);
  const [open, setOpen] = useState(false);

  return (
    <>
      <button
        type="button"
        className={styles.badge}
        onClick={() => setOpen(true)}
        title="Change your course section"
      >
        <GradIcon size={14} />
        <span className={styles.label}>
          {modality ? MODALITY_LABELS[modality] : "Set your section"}
        </span>
      </button>
      <ModalityDialog open={open} onOpenChange={setOpen} />
    </>
  );
}
