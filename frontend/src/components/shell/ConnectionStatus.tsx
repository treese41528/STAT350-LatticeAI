import { useEffect } from "react";
import clsx from "clsx";
import { useAppStore } from "../../stores/appStore";
import { Tooltip } from "../ui/Tooltip";
import styles from "./ConnectionStatus.module.css";

const POLL_MS = 30_000;

/**
 * Topbar health dot: polls /api/health every 30s and listens to
 * navigator.onLine. Green = connected, amber = degraded/busy, red = offline.
 */
export function ConnectionStatus() {
  const health = useAppStore((s) => s.health);
  const online = useAppStore((s) => s.online);
  const refreshHealth = useAppStore((s) => s.refreshHealth);
  const setOnline = useAppStore((s) => s.setOnline);

  useEffect(() => {
    void refreshHealth();
    const timer = setInterval(() => void refreshHealth(), POLL_MS);
    const goOnline = () => {
      setOnline(true);
      void refreshHealth();
    };
    const goOffline = () => setOnline(false);
    window.addEventListener("online", goOnline);
    window.addEventListener("offline", goOffline);
    return () => {
      clearInterval(timer);
      window.removeEventListener("online", goOnline);
      window.removeEventListener("offline", goOffline);
    };
  }, [refreshHealth, setOnline]);

  let state: "ok" | "busy" | "down";
  let label: string;
  if (!online || health == null) {
    state = "down";
    label = !online ? "You're offline" : "Can't reach the tutor service";
  } else if (health.status !== "ok" || health.queueDepth > 3) {
    state = "busy";
    label =
      health.queueDepth > 3
        ? `Busy — ${health.queueDepth} questions queued`
        : "Service degraded — answers may be slow";
  } else {
    state = "ok";
    label = "Connected";
  }

  return (
    <Tooltip content={label}>
      <div className={styles.wrap} role="status" aria-label={label}>
        <span className={clsx(styles.dot, styles[state])} />
        <span className={styles.text}>{state === "ok" ? "Connected" : state === "busy" ? "Busy" : "Offline"}</span>
      </div>
    </Tooltip>
  );
}
