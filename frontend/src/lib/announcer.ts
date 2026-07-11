/**
 * Tiny pub/sub for screen-reader announcements. The streaming region itself
 * is aria-live="off" (token spam would be unusable); instead key moments are
 * routed here and read by the visually-hidden polite live region in
 * <Announcer /> ("Answer ready", queue position changes, errors).
 */

type Listener = (message: string) => void;

const listeners = new Set<Listener>();

export function announce(message: string): void {
  for (const l of listeners) l(message);
}

export function subscribeAnnouncer(listener: Listener): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}
