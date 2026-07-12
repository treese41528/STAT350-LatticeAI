import clsx from "clsx";
import styles from "./Spinner.module.css";

export function Spinner({ size = 18, className }: { size?: number; className?: string }) {
  return (
    <span
      role="status"
      aria-label="Loading"
      className={clsx(styles.spinner, className)}
      style={{ width: size, height: size }}
    />
  );
}
