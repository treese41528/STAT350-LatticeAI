import { useEffect, useState } from "react";
import { subscribeAnnouncer } from "../../lib/announcer";

/**
 * Visually-hidden polite live region. The chat stream itself is
 * aria-live=off; important transitions are announced here instead
 * ("Answer ready", "You're #2 in line", errors).
 */
export function Announcer() {
  const [message, setMessage] = useState("");

  useEffect(
    () =>
      subscribeAnnouncer((msg) => {
        // Clear first so repeating the same message re-announces.
        setMessage("");
        requestAnimationFrame(() => setMessage(msg));
      }),
    [],
  );

  return (
    <div aria-live="polite" role="status" className="visually-hidden">
      {message}
    </div>
  );
}
