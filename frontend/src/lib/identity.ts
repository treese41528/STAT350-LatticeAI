/**
 * Device identity — the ONLY place that knows how the user is identified.
 *
 * Components never touch identity directly; every request flows through
 * `apiFetch` (src/api/http.ts), which attaches the device id. When Purdue CAS
 * lands, this module (and the header apiFetch sends) is the single seam to
 * swap — nothing else changes.
 */

const KEY = "stat350.device";

let cached: string | null = null;

export function getDeviceId(): string {
  if (cached) return cached;
  try {
    let id = localStorage.getItem(KEY);
    if (!id) {
      id = crypto.randomUUID();
      localStorage.setItem(KEY, id);
    }
    cached = id;
    return id;
  } catch {
    // Storage unavailable (private mode etc.) — fall back to a per-session id.
    cached = cached ?? crypto.randomUUID();
    return cached;
  }
}

/**
 * Used by "Clear my data on this device".
 *
 * MUST clear the server's signed HttpOnly device cookie first — JS can't touch
 * it, and if it survives it will mismatch the freshly-minted localStorage id
 * and 401 every request (permanent lockout). Awaited by the caller before
 * reload.
 */
export async function resetDeviceId(): Promise<void> {
  try {
    await fetch("/api/identity/reset", { method: "POST", credentials: "include" });
  } catch {
    /* best effort — proceed to clear local state regardless */
  }
  cached = null;
  try {
    localStorage.removeItem(KEY);
  } catch {
    /* ignore */
  }
}
