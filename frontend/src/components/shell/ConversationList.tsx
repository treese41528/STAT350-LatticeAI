import { useMemo, useState } from "react";
import { Popover } from "radix-ui";
import clsx from "clsx";
import { useChatStore } from "../../stores/chatStore";
import type { ConversationSummary } from "../../api/types";
import { BUCKET_LABELS, relativeTime, timeBucket, type TimeBucket } from "../../lib/time";
import { Dialog } from "../ui/Dialog";
import { Button } from "../ui/Button";
import { IconButton } from "../ui/IconButton";
import { DotsIcon, PencilIcon, TrashIcon } from "../ui/icons";
import styles from "./ConversationList.module.css";

/** Sidebar conversation list, grouped Today / This week / Older. */
export function ConversationList({ onNavigate }: { onNavigate?: () => void }) {
  const order = useChatStore((s) => s.order);
  const conversations = useChatStore((s) => s.conversations);
  const loaded = useChatStore((s) => s.conversationsLoaded);

  const groups = useMemo(() => {
    const buckets: Record<TimeBucket, ConversationSummary[]> = {
      today: [],
      week: [],
      older: [],
    };
    for (const id of order) {
      const c = conversations[id];
      if (c) buckets[timeBucket(c.updatedAt)].push(c);
    }
    return buckets;
  }, [order, conversations]);

  if (order.length === 0) {
    return (
      <p className={styles.empty}>
        {loaded ? "No conversations yet — ask your first question!" : "Loading conversations…"}
      </p>
    );
  }

  return (
    <nav className={styles.list} aria-label="Conversations">
      {(Object.keys(groups) as TimeBucket[]).map((bucket) =>
        groups[bucket].length === 0 ? null : (
          <section key={bucket} className={styles.group}>
            <h3 className={styles.groupLabel}>{BUCKET_LABELS[bucket]}</h3>
            {groups[bucket].map((c) => (
              <ConversationItem key={c.id} conversation={c} onNavigate={onNavigate} />
            ))}
          </section>
        ),
      )}
    </nav>
  );
}

function ConversationItem({
  conversation,
  onNavigate,
}: {
  conversation: ConversationSummary;
  onNavigate?: () => void;
}) {
  const activeId = useChatStore((s) => s.activeId);
  const openConversation = useChatStore((s) => s.openConversation);
  const removeConversation = useChatStore((s) => s.removeConversation);
  const rename = useChatStore((s) => s.rename);

  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(conversation.title);
  const [menuOpen, setMenuOpen] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);

  const isActive = activeId === conversation.id;

  const commitRename = () => {
    setEditing(false);
    if (draft.trim() !== "" && draft.trim() !== conversation.title) {
      void rename(conversation.id, draft);
    } else {
      setDraft(conversation.title);
    }
  };

  if (editing) {
    return (
      <div className={clsx(styles.item, styles.itemEditing)}>
        {/* eslint-disable-next-line jsx-a11y/no-autofocus */}
        <input
          autoFocus
          className={styles.renameInput}
          value={draft}
          aria-label="Conversation title"
          onChange={(e) => setDraft(e.target.value)}
          onBlur={commitRename}
          onKeyDown={(e) => {
            if (e.key === "Enter") commitRename();
            if (e.key === "Escape") {
              setDraft(conversation.title);
              setEditing(false);
            }
          }}
        />
      </div>
    );
  }

  return (
    <div className={clsx(styles.item, isActive && styles.itemActive)}>
      <button
        type="button"
        className={styles.itemButton}
        aria-current={isActive ? "page" : undefined}
        onClick={() => {
          void openConversation(conversation.id);
          onNavigate?.();
        }}
      >
        <span className={styles.title}>{conversation.title}</span>
        <span className={styles.time}>{relativeTime(conversation.updatedAt)}</span>
      </button>

      <Popover.Root open={menuOpen} onOpenChange={setMenuOpen}>
        <Popover.Trigger asChild>
          <IconButton size="sm" label="Conversation options" className={styles.menuBtn}>
            <DotsIcon size={15} />
          </IconButton>
        </Popover.Trigger>
        <Popover.Portal>
          <Popover.Content className={styles.menu} sideOffset={4} align="start">
            <button
              type="button"
              className={styles.menuItem}
              onClick={() => {
                setMenuOpen(false);
                setDraft(conversation.title);
                setEditing(true);
              }}
            >
              <PencilIcon size={14} /> Rename
            </button>
            <button
              type="button"
              className={clsx(styles.menuItem, styles.menuDanger)}
              onClick={() => {
                setMenuOpen(false);
                setConfirmDelete(true);
              }}
            >
              <TrashIcon size={14} /> Delete
            </button>
          </Popover.Content>
        </Popover.Portal>
      </Popover.Root>

      <Dialog
        open={confirmDelete}
        onOpenChange={setConfirmDelete}
        title="Delete conversation?"
        description={`"${conversation.title}" will be permanently removed.`}
      >
        <div className={styles.confirmActions}>
          <Button variant="ghost" onClick={() => setConfirmDelete(false)}>
            Cancel
          </Button>
          <Button
            variant="danger"
            onClick={() => {
              setConfirmDelete(false);
              void removeConversation(conversation.id);
            }}
          >
            Delete
          </Button>
        </div>
      </Dialog>
    </div>
  );
}
