import type { ComponentType, SVGProps } from "react";
import type { Resource } from "../../api/types";
import {
  BookIcon,
  CalendarIcon,
  ExamIcon,
  GradIcon,
  ScrollIcon,
  SimulationIcon,
  VideoIcon,
  WorksheetIcon,
} from "../ui/icons";
import styles from "./ResourceCard.module.css";

const KIND_ICONS: Record<Resource["kind"], ComponentType<SVGProps<SVGSVGElement> & { size?: number }>> = {
  lecture: BookIcon,
  video: VideoIcon,
  worksheet: WorksheetIcon,
  simulation: SimulationIcon,
  syllabus: ScrollIcon,
  schedule: CalendarIcon,
  exam: ExamIcon,
  catalog: GradIcon,
};

const KIND_LABELS: Record<Resource["kind"], string> = {
  lecture: "Lecture",
  video: "Video",
  worksheet: "Worksheet",
  simulation: "Simulation",
  syllabus: "Syllabus",
  schedule: "Schedule",
  exam: "Exam info",
  catalog: "Catalog",
};

export function ResourceCard({ resource }: { resource: Resource }) {
  const Icon = KIND_ICONS[resource.kind] ?? BookIcon;
  if (!/^https?:\/\//i.test(resource.url)) return null;
  return (
    <a
      className={styles.card}
      href={resource.url}
      target="_blank"
      rel="noopener noreferrer"
      title={resource.title}
    >
      <span className={styles.icon}>
        <Icon size={16} />
      </span>
      <span className={styles.body}>
        <span className={styles.kind}>{KIND_LABELS[resource.kind] ?? resource.kind}</span>
        <span className={styles.title}>{resource.title}</span>
        {resource.meta ? <span className={styles.meta}>{resource.meta}</span> : null}
      </span>
    </a>
  );
}
