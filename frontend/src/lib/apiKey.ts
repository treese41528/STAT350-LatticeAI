/**
 * The student's OWN GenAI Studio API key.
 *
 * SECURITY: this is a credential to their Purdue account. It lives ONLY in this
 * browser's localStorage and rides the `X-GenAI-Key` request header (see
 * api/http.ts). It is never sent to telemetry and the server never stores it.
 * We only attach it to requests once the server has confirmed it is USABLE
 * (authenticates AND can read the course materials), so an unusable key never
 * degrades the student's answers.
 */

const KEY = "stat350.genaikey";
const OK = "stat350.genaikey.ok";

export function getOwnKey(): string | null {
  try {
    return localStorage.getItem(KEY);
  } catch {
    return null;
  }
}

/** True only when a key is present AND validated as usable. */
export function ownKeyActive(): boolean {
  try {
    return !!localStorage.getItem(KEY) && localStorage.getItem(OK) === "1";
  } catch {
    return false;
  }
}

export function saveOwnKey(key: string, usable: boolean): void {
  try {
    localStorage.setItem(KEY, key.trim());
    localStorage.setItem(OK, usable ? "1" : "0");
  } catch {
    /* storage unavailable */
  }
}

export function clearOwnKey(): void {
  try {
    localStorage.removeItem(KEY);
    localStorage.removeItem(OK);
  } catch {
    /* ignore */
  }
}
