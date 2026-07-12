/** Date helpers — Intl only, no date libraries. */

const rtf = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });

export function relativeTime(iso: string): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const diffMs = then - Date.now();
  const abs = Math.abs(diffMs);
  const MIN = 60_000;
  const HOUR = 60 * MIN;
  const DAY = 24 * HOUR;
  if (abs < MIN) return rtf.format(Math.round(diffMs / 1000), "second");
  if (abs < HOUR) return rtf.format(Math.round(diffMs / MIN), "minute");
  if (abs < DAY) return rtf.format(Math.round(diffMs / HOUR), "hour");
  if (abs < 7 * DAY) return rtf.format(Math.round(diffMs / DAY), "day");
  if (abs < 30 * DAY) return rtf.format(Math.round(diffMs / (7 * DAY)), "week");
  return rtf.format(Math.round(diffMs / (30 * DAY)), "month");
}

export type TimeBucket = "today" | "week" | "older";

export function timeBucket(iso: string, now: Date = new Date()): TimeBucket {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "older";
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  if (d.getTime() >= startOfToday) return "today";
  if (d.getTime() >= startOfToday - 6 * 24 * 60 * 60 * 1000) return "week";
  return "older";
}

export const BUCKET_LABELS: Record<TimeBucket, string> = {
  today: "Today",
  week: "This week",
  older: "Older",
};
