import clsx from "clsx";
import { useAppStore, MODALITY_LABELS } from "../../stores/appStore";
import type { Modality } from "../../api/types";
import { Dialog } from "../ui/Dialog";
import { CheckIcon } from "../ui/icons";
import styles from "./ModalityDialog.module.css";

const MODALITY_HINTS: Partial<Record<Modality, string>> = {
  flipped: "Videos before class, activities in class",
  traditional: "In-person lectures at West Lafayette",
  indy: "In-person lectures in Indianapolis",
  online: "Fully asynchronous",
  winter: "Condensed winter term (always online)",
  summer: "Condensed summer term (always online)",
};

/** Section picker — used for syllabus/schedule answers tailored to you. */
export function ModalityDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const modalities = useAppStore((s) => s.config.modalities);
  const current = useAppStore((s) => s.modality);
  const setModality = useAppStore((s) => s.setModality);

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title="Which section are you in?"
      description="The tutor uses this to answer syllabus and schedule questions with the right documents."
    >
      <div className={styles.list} role="radiogroup" aria-label="Course section">
        {modalities.map((m) => (
          <button
            key={m}
            type="button"
            role="radio"
            aria-checked={current === m}
            className={clsx(styles.option, current === m && styles.optionOn)}
            onClick={() => {
              void setModality(m);
              onOpenChange(false);
            }}
          >
            <span>
              <span className={styles.optionLabel}>{MODALITY_LABELS[m]}</span>
              {MODALITY_HINTS[m] ? (
                <span className={styles.optionHint}>{MODALITY_HINTS[m]}</span>
              ) : null}
            </span>
            {current === m && <CheckIcon size={16} className={styles.check} />}
          </button>
        ))}
      </div>
    </Dialog>
  );
}
