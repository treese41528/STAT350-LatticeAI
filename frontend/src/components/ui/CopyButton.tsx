import { useEffect, useRef, useState } from "react";
import { IconButton } from "./IconButton";
import { CheckIcon, CopyIcon } from "./icons";

export function CopyButton({ text, label = "Copy" }: { text: string; label?: string }) {
  const [copied, setCopied] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
    },
    [],
  );

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      if (timer.current) clearTimeout(timer.current);
      timer.current = setTimeout(() => setCopied(false), 1600);
    } catch {
      /* clipboard unavailable */
    }
  };

  return (
    <IconButton size="sm" label={copied ? "Copied" : label} onClick={() => void copy()}>
      {copied ? <CheckIcon size={15} style={{ color: "var(--success)" }} /> : <CopyIcon size={15} />}
    </IconButton>
  );
}
