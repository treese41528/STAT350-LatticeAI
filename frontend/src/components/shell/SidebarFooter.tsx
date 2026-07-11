import { IconButton } from "../ui/IconButton";
import { GearIcon } from "../ui/icons";
import { ModalityBadge } from "../settings/ModalityBadge";
import styles from "./SidebarFooter.module.css";

export function SidebarFooter({ onOpenSettings }: { onOpenSettings: () => void }) {
  return (
    <div className={styles.footer}>
      <ModalityBadge />
      <IconButton label="Settings" onClick={onOpenSettings}>
        <GearIcon size={18} />
      </IconButton>
    </div>
  );
}
