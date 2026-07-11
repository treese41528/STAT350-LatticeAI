import { describe, expect, it } from "vitest";
import type { Element, Root, Text } from "hast";
import rehypeCitations from "../lib/rehypeCitations";

function p(...children: (Element | Text)[]): Element {
  return { type: "element", tagName: "p", properties: {}, children };
}

function text(value: string): Text {
  return { type: "text", value };
}

function root(...children: Element[]): Root {
  return { type: "root", children };
}

function run(tree: Root, max: number): Root {
  rehypeCitations({ max })(tree);
  return tree;
}

function tagNames(el: Element): string[] {
  return el.children.map((c) => (c.type === "element" ? c.tagName : c.type));
}

describe("rehypeCitations", () => {
  it("splits text nodes around [n] markers and emits cite-n elements", () => {
    const tree = root(p(text("See [1] and [2] for details.")));
    run(tree, 2);
    const para = tree.children[0] as Element;
    expect(tagNames(para)).toEqual(["text", "cite-n", "text", "cite-n", "text"]);
    const cite1 = para.children[1] as Element;
    expect(cite1.properties?.dataN).toBe("1");
    const cite2 = para.children[3] as Element;
    expect(cite2.properties?.dataN).toBe("2");
    expect((para.children[0] as Text).value).toBe("See ");
    expect((para.children[2] as Text).value).toBe(" and ");
    expect((para.children[4] as Text).value).toBe(" for details.");
  });

  it("leaves markers above max as literal text (no phantom citations)", () => {
    const tree = root(p(text("Real [1] but fake [7].")));
    run(tree, 1);
    const para = tree.children[0] as Element;
    expect(tagNames(para)).toEqual(["text", "cite-n", "text"]);
    expect((para.children[2] as Text).value).toBe(" but fake [7].");
  });

  it("ignores [0] and numbers longer than two digits", () => {
    const tree = root(p(text("Edge [0] and [123] stay.")));
    run(tree, 99);
    const para = tree.children[0] as Element;
    expect(tagNames(para)).toEqual(["text"]);
  });

  it("never touches text inside code or pre", () => {
    const code: Element = {
      type: "element",
      tagName: "code",
      properties: {},
      children: [text("x[1] <- 5")],
    };
    const pre: Element = { type: "element", tagName: "pre", properties: {}, children: [code] };
    const tree = root(pre);
    run(tree, 5);
    expect((code.children[0] as Text).value).toBe("x[1] <- 5");
  });

  it("never touches KaTeX output (class contains katex)", () => {
    const katexSpan: Element = {
      type: "element",
      tagName: "span",
      properties: { className: ["katex"] },
      children: [text("[1, 2]")],
    };
    const tree = root(p(katexSpan));
    run(tree, 5);
    expect((katexSpan.children[0] as Text).value).toBe("[1, 2]");
  });

  it("never nests markers inside links", () => {
    const link: Element = {
      type: "element",
      tagName: "a",
      properties: { href: "https://example.edu" },
      children: [text("see [1]")],
    };
    const tree = root(p(link));
    run(tree, 5);
    expect((link.children[0] as Text).value).toBe("see [1]");
  });

  it("does nothing when max is 0", () => {
    const tree = root(p(text("Mentions [1] with no citations loaded.")));
    run(tree, 0);
    const para = tree.children[0] as Element;
    expect(tagNames(para)).toEqual(["text"]);
  });
});
