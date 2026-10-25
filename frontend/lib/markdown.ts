// A small, safe markdown reader for blue's end-of-day reports. Owner: Dev R.
//
// It turns text into plain data (blocks and inline runs) and the React side builds elements from that, so nothing is ever injected as
// HTML and a link is only ever its text. Headings, paragraphs, bullet and numbered lists, pipe tables, code fences, rules, and
// **bold**, *italic* and `code` inside a line. Anything else is a paragraph. Deliberately not a full CommonMark.

export type MdBlock =
  | { t: "h"; level: 1 | 2 | 3 | 4; text: string }
  | { t: "p"; text: string }
  | { t: "ul"; items: string[] }
  | { t: "ol"; items: string[] }
  | { t: "table"; head: string[]; rows: string[][] }
  | { t: "code"; text: string }
  | { t: "hr" };

export type MdInline = { t: "text" | "b" | "i" | "code"; text: string };

const cells = (line: string): string[] => line.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((c) => c.trim());
const isRule = (line: string) => /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/.test(line);

export function parseMarkdown(src: string): MdBlock[] {
  const lines = src.replace(/\r\n?/g, "\n").split("\n");
  const out: MdBlock[] = [];
  let i = 0;
  let para: string[] = [];
  const flush = () => { if (para.length) { out.push({ t: "p", text: para.join(" ") }); para = []; } };

  while (i < lines.length) {
    const line = lines[i]!;
    if (/^\s*$/.test(line)) { flush(); i++; continue; }

    if (/^\s*```/.test(line)) {
      flush();
      const body: string[] = [];
      i++;
      while (i < lines.length && !/^\s*```/.test(lines[i]!)) body.push(lines[i++]!);
      i++; // the closing fence (or the end)
      out.push({ t: "code", text: body.join("\n") });
      continue;
    }

    const h = /^(#{1,6})\s+(.*?)\s*#*\s*$/.exec(line);
    if (h) { flush(); out.push({ t: "h", level: Math.min(4, h[1]!.length) as 1 | 2 | 3 | 4, text: h[2]! }); i++; continue; }

    if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(line)) { flush(); out.push({ t: "hr" }); i++; continue; }

    if (/^\s*\|.*\|\s*$/.test(line) && i + 1 < lines.length && isRule(lines[i + 1]!)) {
      flush();
      const head = cells(line);
      const rows: string[][] = [];
      i += 2;
      while (i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i]!)) rows.push(cells(lines[i++]!));
      out.push({ t: "table", head, rows });
      continue;
    }

    const ul = /^\s*[-*+]\s+(.*)$/.exec(line);
    const ol = /^\s*\d+[.)]\s+(.*)$/.exec(line);
    if (ul || ol) {
      flush();
      const items: string[] = [];
      const re = ul ? /^\s*[-*+]\s+(.*)$/ : /^\s*\d+[.)]\s+(.*)$/;
      while (i < lines.length) {
        const m = re.exec(lines[i]!);
        if (m) { items.push(m[1]!); i++; continue; }
        // an indented continuation belongs to the item above it
        if (items.length && /^\s{2,}\S/.test(lines[i]!) && !/^\s*([-*+]|\d+[.)])\s/.test(lines[i]!)) { items[items.length - 1] += ` ${lines[i]!.trim()}`; i++; continue; }
        break;
      }
      out.push({ t: ul ? "ul" : "ol", items });
      continue;
    }

    para.push(line.trim());
    i++;
  }
  flush();
  return out;
}

/** **bold**, *italic*, `code`; links and images keep only their text. */
export function parseInline(text: string): MdInline[] {
  const plain = text.replace(/!?\[([^\]]*)\]\((?:[^()]|\([^()]*\))*\)/g, "$1");
  const out: MdInline[] = [];
  const re = /(`[^`]+`|\*\*[^*]+\*\*|\*[^*\s][^*]*\*)/g;
  let last = 0;
  for (let m = re.exec(plain); m; m = re.exec(plain)) {
    if (m.index > last) out.push({ t: "text", text: plain.slice(last, m.index) });
    const tok = m[0];
    if (tok.startsWith("`")) out.push({ t: "code", text: tok.slice(1, -1) });
    else if (tok.startsWith("**")) out.push({ t: "b", text: tok.slice(2, -2) });
    else out.push({ t: "i", text: tok.slice(1, -1) });
    last = m.index + tok.length;
  }
  if (last < plain.length) out.push({ t: "text", text: plain.slice(last) });
  return out;
}
