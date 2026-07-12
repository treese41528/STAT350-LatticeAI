import { describe, expect, it } from "vitest";
import { splitBlocks, splitStable } from "../lib/streamingMarkdown";

describe("splitStable — code fences", () => {
  it("keeps fully closed fences stable", () => {
    const md = "Intro\n\n```r\nmean(x)\n```\n\nOutro";
    expect(splitStable(md)).toEqual({ stable: md, tail: "" });
  });

  it("cuts before an unclosed fence", () => {
    const md = "Intro\n\n```r\nmean(x)\nsd(x)";
    const { stable, tail } = splitStable(md);
    expect(stable).toBe("Intro\n\n");
    expect(tail).toBe("```r\nmean(x)\nsd(x)");
  });

  it("ignores $ and [ inside an open fence", () => {
    const md = "Text\n\n```r\nx$col <- v[1]\n";
    const { stable, tail } = splitStable(md);
    expect(stable).toBe("Text\n\n");
    expect(tail.startsWith("```r")).toBe(true);
  });
});

describe("splitStable — display math", () => {
  it("keeps closed $$ stable", () => {
    const md = "The statistic:\n\n$$t = \\frac{\\bar{x} - \\mu_0}{s/\\sqrt{n}}$$\n\ndone";
    expect(splitStable(md)).toEqual({ stable: md, tail: "" });
  });

  it("cuts before an unclosed $$", () => {
    const md = "The statistic:\n\n$$t = \\frac{\\bar{x}";
    const { stable, tail } = splitStable(md);
    expect(stable).toBe("The statistic:\n\n");
    expect(tail).toBe("$$t = \\frac{\\bar{x}");
  });

  it("does not treat a single $ inside $$ ... $$ as inline math", () => {
    const md = "$$ a $ b $$ after";
    expect(splitStable(md)).toEqual({ stable: md, tail: "" });
  });
});

describe("splitStable — inline math", () => {
  it("keeps closed $...$ stable", () => {
    const md = "So $\\mu$ is the mean.";
    expect(splitStable(md)).toEqual({ stable: md, tail: "" });
  });

  it("cuts before a trailing unclosed $", () => {
    const md = "So $\\mu is the";
    const { stable, tail } = splitStable(md);
    expect(stable).toBe("So ");
    expect(tail).toBe("$\\mu is the");
  });

  it("treats escaped \\$ as plain text, not math", () => {
    const md = "It costs \\$5 total.";
    expect(splitStable(md)).toEqual({ stable: md, tail: "" });
  });

  it("handles escaped \\$ inside real math", () => {
    const md = "Price $p = \\$5$ done";
    expect(splitStable(md)).toEqual({ stable: md, tail: "" });
  });
});

describe("splitStable — inline code", () => {
  it("cuts before an unclosed backtick", () => {
    const { stable, tail } = splitStable("Use `qt(");
    expect(stable).toBe("Use ");
    expect(tail).toBe("`qt(");
  });

  it("ignores $ inside closed inline code", () => {
    const md = "Use `x$col` here.";
    expect(splitStable(md)).toEqual({ stable: md, tail: "" });
  });
});

describe("splitStable — links and citations", () => {
  it("keeps complete links stable", () => {
    const md = "See [chapter 8](https://example.edu/ch8) for more.";
    expect(splitStable(md)).toEqual({ stable: md, tail: "" });
  });

  it("cuts a trailing partial link text", () => {
    const { stable, tail } = splitStable("See [chapter");
    expect(stable).toBe("See ");
    expect(tail).toBe("[chapter");
  });

  it("cuts a partial link URL", () => {
    const { stable, tail } = splitStable("See [chapter 8](https://example.ed");
    expect(stable).toBe("See ");
    expect(tail).toBe("[chapter 8](https://example.ed");
  });

  it("keeps citation markers [1] stable when followed by text", () => {
    const md = "As shown in [1] and [2], the CLT applies.";
    expect(splitStable(md)).toEqual({ stable: md, tail: "" });
  });

  it("holds back a trailing ] (could become a link)", () => {
    const { stable, tail } = splitStable("As shown in [12]");
    expect(stable).toBe("As shown in ");
    expect(tail).toBe("[12]");
  });
});

describe("splitStable — misc", () => {
  it("passes plain text through untouched", () => {
    const md = "Just a sentence with no constructs at all.";
    expect(splitStable(md)).toEqual({ stable: md, tail: "" });
  });

  it("handles empty input", () => {
    expect(splitStable("")).toEqual({ stable: "", tail: "" });
  });

  it("cuts only the LAST unclosed construct", () => {
    const md = "Closed $x$ then `code` then $$y$$ then $open";
    const { stable, tail } = splitStable(md);
    expect(stable).toBe("Closed $x$ then `code` then $$y$$ then ");
    expect(tail).toBe("$open");
  });
});

describe("splitBlocks", () => {
  it("splits on blank lines", () => {
    expect(splitBlocks("a\n\nb\n\nc")).toEqual(["a", "b", "c"]);
  });

  it("does not split inside code fences", () => {
    const md = "```r\nline1\n\nline2\n```\n\nafter";
    expect(splitBlocks(md)).toEqual(["```r\nline1\n\nline2\n```", "after"]);
  });

  it("does not split inside display math with blank lines", () => {
    const md = "$$\na = 1\n\nb = 2\n$$\n\nafter";
    expect(splitBlocks(md)).toEqual(["$$\na = 1\n\nb = 2\n$$", "after"]);
  });

  it("returns no blocks for empty input", () => {
    expect(splitBlocks("")).toEqual([]);
  });
});
