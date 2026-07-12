import { useState } from "react";
import clsx from "clsx";
import { Dialog } from "../ui/Dialog";
import { Button } from "../ui/Button";
import { DOWN_TAGS } from "./tags";
import styles from "./FeedbackDialog.module.css";

/**
 * Thumbs-down dialog. Submitting requires at least one tag OR a comment, so
 * every negative rating is actionable for the course staff.
 */
export function FeedbackDialog({
  open,
  onOpenChange,
  onSubmit,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSubmit: (tags: string[], comment?: string) => void;
}) {
  const [tags, setTags] = useState<string[]>([]);
  const [comment, setComment] = useState("");

  const valid = tags.length > 0 || comment.trim() !== "";

  const toggle = (id: string) =>
    setTags((prev) => (prev.includes(id) ? prev.filter((t) => t !== id) : [...prev, id]));

  const submit = () => {
    if (!valid) return;
    onSubmit(tags, comment.trim() === "" ? undefined : comment.trim());
    setTags([]);
    setComment("");
    onOpenChange(false);
  };

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title="What went wrong?"
      description="Pick at least one issue (or leave a comment) so we can fix it."
    >
      <div className={styles.tagGrid}>
        {DOWN_TAGS.map((tag) => (
          <button
            key={tag.id}
            type="button"
            className={clsx(styles.tag, tags.includes(tag.id) && styles.tagOn)}
            aria-pressed={tags.includes(tag.id)}
            onClick={() => toggle(tag.id)}
          >
            {tag.label}
          </button>
        ))}
      </div>
      <label className={styles.commentLabel}>
        Anything else? <span className={styles.optional}>(optional)</span>
        <textarea
          className={styles.comment}
          rows={3}
          value={comment}
          onChange={(e) => setComment(e.target.value)}
          placeholder="Tell us what you expected…"
        />
      </label>
      <div className={styles.actions}>
        <Button variant="ghost" onClick={() => onOpenChange(false)}>
          Cancel
        </Button>
        <Button onClick={submit} disabled={!valid}>
          Send feedback
        </Button>
      </div>
    </Dialog>
  );
}
