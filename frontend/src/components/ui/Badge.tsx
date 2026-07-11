import type { HTMLAttributes } from "react";
import clsx from "clsx";
import styles from "./Badge.module.css";

export interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  tone?: "gold" | "steel" | "gray" | "danger";
}

export function Badge({ tone = "gray", className, ...props }: BadgeProps) {
  return <span className={clsx(styles.badge, styles[tone], className)} {...props} />;
}
