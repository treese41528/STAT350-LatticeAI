import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { MessageMarkdown } from "../components/markdown/MessageMarkdown";
import type { Citation } from "../api/types";

const CITATIONS: Citation[] = [
  {
    n: 1,
    source: "webbook",
    title: "Chapter 8.2",
    snippet: "t procedures snippet",
    similarity: 0.9,
    url: "https://example.edu/ch8",
  },
];

describe("MessageMarkdown", () => {
  it("renders [1] as an interactive citation chip", () => {
    render(<MessageMarkdown content="As shown in [1]." citations={CITATIONS} />);
    const chip = screen.getByRole("button", { name: /citation 1/i });
    expect(chip).toHaveTextContent("1");
  });

  it("drops raw HTML instead of rendering it (no rehype-raw invariant)", () => {
    const { container } = render(
      <MessageMarkdown
        content={'Safe <img src=x onerror="window.__pwned=1"> text <script>window.__x=1</script>'}
        citations={[]}
      />,
    );
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("script")).toBeNull();
    expect(container.textContent).toContain("Safe");
  });

  it("renders http links with target=_blank and rel=noopener", () => {
    const { container } = render(
      <MessageMarkdown content="See [ch 8](https://example.edu/ch8)." citations={[]} />,
    );
    const a = container.querySelector("a");
    expect(a).not.toBeNull();
    expect(a?.getAttribute("target")).toBe("_blank");
    expect(a?.getAttribute("rel")).toContain("noopener");
  });

  it("renders non-http links as plain text", () => {
    const { container } = render(
      <MessageMarkdown content="Bad [link](javascript:alert(1))." citations={[]} />,
    );
    expect(container.querySelector("a")).toBeNull();
    expect(container.textContent).toContain("link");
  });

  it("turns the BEYOND banner line into a note, preserving the message", () => {
    const { container } = render(
      <MessageMarkdown
        content={
        "Intro.\n\n>>> BEYOND STAT 350 SCOPE: Enrichment for curious learners; not required for this course. <<<\n\nMore."
        }
        citations={[]}
      />,
    );
    const note = container.querySelector('[role="note"]');
    expect(note).not.toBeNull();
    expect(note?.textContent).toContain("Enrichment for curious learners");
  });

  it("renders the streaming tail as plain dimmed text", () => {
    const { container } = render(
      <MessageMarkdown content={"Stable text.\n\n$$t = \\frac{1}"} citations={[]} streaming />,
    );
    // The unfinished math must NOT be handed to KaTeX.
    expect(container.querySelector(".katex")).toBeNull();
    expect(container.textContent).toContain("$$t =");
  });
});
