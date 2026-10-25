"use client";
// Renders lib/markdown.ts's blocks as elements. No HTML is ever injected. Owner: Dev R.
import { Fragment, useMemo } from "react";
import { parseInline, parseMarkdown, type MdBlock } from "@/lib/markdown";

function Inline({ text }: { text: string }) {
  return (
    <>
      {parseInline(text).map((r, i) => (r.t === "b" ? <b key={i}>{r.text}</b> : r.t === "i" ? <i key={i}>{r.text}</i> : r.t === "code" ? <code key={i}>{r.text}</code> : <Fragment key={i}>{r.text}</Fragment>))}
    </>
  );
}

function Block({ b }: { b: MdBlock }) {
  switch (b.t) {
    case "h": return b.level === 1 ? <h3><Inline text={b.text} /></h3> : <h4><Inline text={b.text} /></h4>;
    case "p": return <p><Inline text={b.text} /></p>;
    case "ul": return <ul>{b.items.map((it, i) => <li key={i}><Inline text={it} /></li>)}</ul>;
    case "ol": return <ol>{b.items.map((it, i) => <li key={i}><Inline text={it} /></li>)}</ol>;
    case "code": return <pre>{b.text}</pre>;
    case "hr": return <hr />;
    case "table":
      return (
        <table>
          <thead><tr>{b.head.map((c, i) => <th key={i}><Inline text={c} /></th>)}</tr></thead>
          <tbody>{b.rows.map((r, i) => <tr key={i}>{r.map((c, j) => <td key={j}><Inline text={c} /></td>)}</tr>)}</tbody>
        </table>
      );
  }
}

export function Markdown({ text }: { text: string }) {
  const blocks = useMemo(() => parseMarkdown(text), [text]);
  return <div className="md">{blocks.map((b, i) => <Block key={i} b={b} />)}</div>;
}
