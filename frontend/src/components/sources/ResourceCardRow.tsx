import type { Resource } from "../../api/types";
import { ResourceCard } from "./ResourceCard";
import styles from "./ResourceCardRow.module.css";

export function ResourceCardRow({ resources }: { resources: Resource[] }) {
  if (resources.length === 0) return null;
  return (
    <div className={styles.row} aria-label="Related course resources">
      {resources.map((r, i) => (
        <ResourceCard key={`${r.url}-${i}`} resource={r} />
      ))}
    </div>
  );
}
