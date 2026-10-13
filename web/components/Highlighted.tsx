/** Source text with evidence spans highlighted. Offsets are UTF-16 code units from the API (D24), which is how
 * JavaScript strings index, so slicing is exact even with Hindi text or emoji. */
export function Highlighted({ text, spans }: { text: string; spans: { start: number; end: number; eligible: boolean }[] }) {
  const ordered = [...spans].filter((s) => s.end > s.start).sort((a, b) => a.start - b.start);
  const parts: React.ReactNode[] = [];
  let at = 0;
  ordered.forEach((span, index) => {
    const start = Math.max(span.start, at);
    if (start > at) parts.push(text.slice(at, start));
    if (span.end > start) {
      parts.push(
        <mark key={index} className={span.eligible ? "bg-teal-100" : "bg-red-100 line-through"} title={span.eligible ? "evidence" : "evidence not eligible"}>
          {text.slice(start, span.end)}
        </mark>,
      );
    }
    at = Math.max(at, span.end);
  });
  if (at < text.length) parts.push(text.slice(at));
  return <div className="whitespace-pre-wrap break-words leading-6">{parts}</div>;
}
