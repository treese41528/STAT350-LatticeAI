import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { MessageMarkdown } from "../components/markdown/MessageMarkdown";
import { ResourceCard } from "../components/sources/ResourceCard";
import type { Citation, Resource } from "../api/types";

/**
 * "Formulas display correctly" and "links work when returned in an answer".
 * jsdom runs the real react-markdown + rehype-katex pipeline, so a rendered
 * .katex node (with no .katex-error) is real evidence KaTeX parsed the TeX.
 */

describe("formula rendering (KaTeX)", () => {
  it("renders inline math to KaTeX without errors", () => {
    const { container } = render(
      <MessageMarkdown content={"The estimator is $\\bar{x} \\pm z_{0.05}$."} citations={[]} />,
    );
    expect(container.querySelector(".katex")).not.toBeNull();
    expect(container.querySelector(".katex-error")).toBeNull();
  });

  it("renders display math as a centered block", () => {
    // display math as its own paragraph — how the model actually emits it
    const { container } = render(
      <MessageMarkdown
        content={"The test statistic is:\n\n$$ t = \\frac{\\bar{x} - \\mu_0}{s / \\sqrt{n}} $$\n\nCompare to the t distribution."}
        citations={[]}
      />,
    );
    expect(container.querySelector(".katex-display")).not.toBeNull();
    expect(container.querySelector(".katex-error")).toBeNull();
  });

  it("renders a realistic multi-formula stats answer (CI + test statistic)", () => {
    const content = [
      "For a 90% CI use the upper-tail critical value $z_{0.05} = 1.645$:",
      "",
      "$$ \\bar{x} \\pm z_{0.05}\\,\\frac{\\sigma}{\\sqrt{n}} $$",
      "",
      "The pooled test statistic is $t = \\dfrac{\\bar{x}_A - \\bar{x}_B}{s_p\\sqrt{1/n_A + 1/n_B}}$.",
    ].join("\n");
    const { container } = render(<MessageMarkdown content={content} citations={[]} />);
    // multiple KaTeX renders, none errored
    expect(container.querySelectorAll(".katex").length).toBeGreaterThanOrEqual(3);
    expect(container.querySelector(".katex-error")).toBeNull();
    // surrounding prose still present
    expect(container.textContent).toContain("upper-tail critical value");
  });

  it("does not treat a lone dollar sign in prose as math", () => {
    const { container } = render(
      <MessageMarkdown content={"Edfinity costs $35 for the semester."} citations={[]} />,
    );
    expect(container.querySelector(".katex")).toBeNull();
    expect(container.textContent).toContain("$35");
  });
});

describe("resource card links", () => {
  const kinds: Resource["kind"][] = [
    "lecture", "video", "worksheet", "simulation", "syllabus", "schedule", "exam", "catalog",
  ];

  it("renders each kind as a safe external link with the right href", () => {
    for (const kind of kinds) {
      const url = `https://treese41528.github.io/STAT350/${kind}.html`;
      const { container, unmount } = render(
        <ResourceCard resource={{ kind, title: `${kind} title`, url, meta: "meta" }} />,
      );
      const a = container.querySelector("a");
      expect(a?.getAttribute("href")).toBe(url);
      expect(a?.getAttribute("target")).toBe("_blank");
      expect(a?.getAttribute("rel")).toContain("noopener");
      unmount();
    }
  });

  it("refuses to render a non-http resource url (defense in depth)", () => {
    const { container } = render(
      <ResourceCard
        resource={{ kind: "lecture", title: "x", url: "javascript:alert(1)" }}
      />,
    );
    expect(container.querySelector("a")).toBeNull();
  });
});

describe("citation markers in an answer", () => {
  const citations: Citation[] = [
    { n: 1, source: "webbook", title: "9.2 CI for the mean", snippet: "z interval", similarity: 0.86,
      url: "https://treese41528.github.io/STAT350/Website/chapter9/lectures/9-2-ci-sigma-known.html" },
    { n: 2, source: "transcript", title: "Lecture 9.2", snippet: "in lecture", similarity: 0.83 },
  ];

  it("renders every [n] marker that has a backing citation", () => {
    render(
      <MessageMarkdown content={"Use the z-interval [1], as covered in lecture [2]."} citations={citations} />,
    );
    expect(screen.getByRole("button", { name: /citation 1/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /citation 2/i })).toBeInTheDocument();
  });

  it("does not render a marker with no backing citation", () => {
    render(<MessageMarkdown content={"Bogus cite [7]."} citations={citations} />);
    expect(screen.queryByRole("button", { name: /citation 7/i })).toBeNull();
  });
});
