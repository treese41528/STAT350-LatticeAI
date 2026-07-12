import { useState } from "react";
import { Popover } from "radix-ui";
import clsx from "clsx";
import { useChatStore } from "../../stores/chatStore";
import type { Message } from "../../api/types";
import { IconButton } from "../ui/IconButton";
import { ThumbsDownIcon, ThumbsUpIcon } from "../ui/icons";
import { FeedbackDialog } from "./FeedbackDialog";
import { UP_TAGS } from "./tags";
import styles from "./FeedbackButtons.module.css";

/**
 * Thumbs up: one tap records the rating; a light popover then offers optional
 * "what worked" tags. Thumbs down: opens FeedbackDialog, which requires at
 * least one tag or a comment before submitting.
 */
export function FeedbackButtons({ message }: { message: Message }) {
  const submitFeedback = useChatStore((s) => s.submitFeedback);
  const [downOpen, setDownOpen] = useState(false);
  const [upTagsOpen, setUpTagsOpen] = useState(false);
  const [upTags, setUpTags] = useState<string[]>([]);

  const rating = message.feedback?.rating;

  const handleUp = () => {
    if (rating === "up") return;
    void submitFeedback(message.id, { rating: "up", tags: [] });
    setUpTagsOpen(true);
  };

  const toggleUpTag = (id: string) => {
    const next = upTags.includes(id) ? upTags.filter((t) => t !== id) : [...upTags, id];
    setUpTags(next);
    void submitFeedback(message.id, { rating: "up", tags: next });
  };

  return (
    <>
      <Popover.Root open={upTagsOpen} onOpenChange={setUpTagsOpen}>
        <Popover.Anchor asChild>
          <IconButton
            size="sm"
            label="Good answer"
            aria-pressed={rating === "up"}
            className={clsx(rating === "up" && styles.activeUp)}
            onClick={handleUp}
          >
            <ThumbsUpIcon size={15} />
          </IconButton>
        </Popover.Anchor>
        <Popover.Portal>
          <Popover.Content className={styles.upPopover} sideOffset={6} align="start">
            <div className={styles.upTitle}>Thanks! What worked?</div>
            <div className={styles.tagRow}>
              {UP_TAGS.map((tag) => (
                <button
                  key={tag.id}
                  type="button"
                  className={clsx(styles.tag, upTags.includes(tag.id) && styles.tagOn)}
                  aria-pressed={upTags.includes(tag.id)}
                  onClick={() => toggleUpTag(tag.id)}
                >
                  {tag.label}
                </button>
              ))}
            </div>
          </Popover.Content>
        </Popover.Portal>
      </Popover.Root>

      <IconButton
        size="sm"
        label="Needs work"
        aria-pressed={rating === "down"}
        className={clsx(rating === "down" && styles.activeDown)}
        onClick={() => setDownOpen(true)}
      >
        <ThumbsDownIcon size={15} />
      </IconButton>

      <FeedbackDialog
        open={downOpen}
        onOpenChange={setDownOpen}
        onSubmit={(tags, comment) =>
          void submitFeedback(message.id, { rating: "down", tags, comment })
        }
      />
    </>
  );
}
