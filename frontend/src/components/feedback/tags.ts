/** Feedback tag vocabulary — ids are part of the API contract with the backend. */

export interface FeedbackTag {
  id: string;
  label: string;
}

export const DOWN_TAGS: FeedbackTag[] = [
  { id: "wrong-math", label: "Incorrect formula or calculation" },
  { id: "notation", label: "Not the course's notation" },
  { id: "bad-sources", label: "Sources irrelevant or missing" },
  { id: "broken-link", label: "Link broken or wrong page" },
  { id: "too-much-help", label: "Gave away the answer" },
  { id: "too-little-help", label: "Too vague to act on" },
  { id: "off-scope", label: "Beyond/off the course material" },
  { id: "missed-question", label: "Didn't address my question" },
];

export const UP_TAGS: FeedbackTag[] = [
  { id: "clear", label: "Clear explanation" },
  { id: "good-sources", label: "Right sources" },
  { id: "right-level", label: "Right amount of help" },
];
