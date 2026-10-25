import { describe, expect, it } from "vitest";
import { parseInline, parseMarkdown } from "./markdown";

describe("markdown reader", () => {
  it("reads headings, paragraphs and lists", () => {
    const md = "# Day 3\n\nBlue checked 12 payments\nand stopped two.\n\n- first\n- second\n  more of second\n\n1. one\n2) two\n";
    expect(parseMarkdown(md)).toEqual([
      { t: "h", level: 1, text: "Day 3" },
      { t: "p", text: "Blue checked 12 payments and stopped two." },
      { t: "ul", items: ["first", "second more of second"] },
      { t: "ol", items: ["one", "two"] },
    ]);
  });

  it("reads a pipe table, a code fence and a rule", () => {
    const md = "| Rule | Fired |\n| --- | ---: |\n| near_threshold | 3 |\n| recent_bank_change | 1 |\n\n---\n\n```\nGET /reports/1\n```\n";
    expect(parseMarkdown(md)).toEqual([
      { t: "table", head: ["Rule", "Fired"], rows: [["near_threshold", "3"], ["recent_bank_change", "1"]] },
      { t: "hr" },
      { t: "code", text: "GET /reports/1" },
    ]);
  });

  it("caps heading depth at 4 and survives an unclosed fence and empty input", () => {
    expect(parseMarkdown("###### deep")[0]).toEqual({ t: "h", level: 4, text: "deep" });
    expect(parseMarkdown("```\nnever closed")).toEqual([{ t: "code", text: "never closed" }]);
    expect(parseMarkdown("")).toEqual([]);
    expect(parseMarkdown("\n\n  \n")).toEqual([]);
  });

  it("reads bold, italic and code, and keeps only the text of links and images", () => {
    expect(parseInline("a **b** and *c* and `d`")).toEqual([
      { t: "text", text: "a " }, { t: "b", text: "b" }, { t: "text", text: " and " }, { t: "i", text: "c" }, { t: "text", text: " and " }, { t: "code", text: "d" },
    ]);
    expect(parseInline("see [the vendor](javascript:alert(1)) and ![x](http://e/x.png)")).toEqual([{ t: "text", text: "see the vendor and x" }]);
  });

  it("never produces markup: html stays text", () => {
    const blocks = parseMarkdown("<img src=x onerror=alert(1)> **bold**");
    expect(blocks).toEqual([{ t: "p", text: "<img src=x onerror=alert(1)> **bold**" }]);
    expect(parseInline("<script>x</script>")).toEqual([{ t: "text", text: "<script>x</script>" }]);
  });
});
