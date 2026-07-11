import { apiFetch } from "./http";
import { getDeviceId } from "../lib/identity";

/**
 * Batched analytics events: POST /api/events {events: [{type, payload, ts}]}.
 * Flushed every 15s / 20 events, and via navigator.sendBeacon on page hide
 * (sendBeacon cannot set headers, so the device id rides in the body there).
 */

interface AppEvent {
  type: string;
  payload: Record<string, unknown>;
  ts: string;
}

const FLUSH_INTERVAL_MS = 15_000;
const FLUSH_THRESHOLD = 20;

let queue: AppEvent[] = [];
let timer: ReturnType<typeof setTimeout> | null = null;
let installed = false;

export function trackEvent(type: string, payload: Record<string, unknown> = {}): void {
  queue.push({ type, payload, ts: new Date().toISOString() });
  if (queue.length >= FLUSH_THRESHOLD) {
    void flushEvents();
  } else if (!timer) {
    timer = setTimeout(() => void flushEvents(), FLUSH_INTERVAL_MS);
  }
}

export async function flushEvents(): Promise<void> {
  if (timer) {
    clearTimeout(timer);
    timer = null;
  }
  if (queue.length === 0) return;
  const events = queue;
  queue = [];
  try {
    await apiFetch("/api/events", { method: "POST", body: JSON.stringify({ events }) });
  } catch {
    // Best-effort: drop on failure rather than grow unboundedly.
  }
}

function beaconFlush(): void {
  if (queue.length === 0) return;
  const events = queue;
  queue = [];
  try {
    const blob = new Blob([JSON.stringify({ events, deviceId: getDeviceId() })], {
      type: "application/json",
    });
    navigator.sendBeacon("/api/events", blob);
  } catch {
    /* best-effort */
  }
}

export function installEventFlushHandlers(): void {
  if (installed) return;
  installed = true;
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") beaconFlush();
  });
  window.addEventListener("pagehide", beaconFlush);
}
