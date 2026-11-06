export type Format = 'bold' | 'italic' | 'heading' | 'bullets' | 'numbers' | 'link' | 'quote' | 'code';
export function formatMarkdown(value: string, start: number, end: number, format: Format) {
  let selected = value.slice(start, end);
  let insert: string;
  if (format === 'bold' || format === 'italic' || format === 'code') {
    const marker = format === 'bold' ? '**' : format === 'italic' ? '*' : '`';
    selected ||= 'text'; insert = marker + selected + marker;
    return { value: value.slice(0, start) + insert + value.slice(end), start: start + marker.length, end: start + marker.length + selected.length };
  }
  if (format === 'link') {
    insert = `[${selected || 'link text'}](https://example.com)`;
    const offset = insert.indexOf('https://');
    return { value: value.slice(0, start) + insert + value.slice(end), start: start + offset, end: start + insert.length - 1 };
  }
  start = start === 0 ? 0 : value.lastIndexOf('\n', start - 1) + 1;
  selected = value.slice(start, end);
  insert = selected.split('\n').map((line, i) => (format === 'heading' ? '## ' : format === 'quote' ? '> ' : format === 'numbers' ? `${i + 1}. ` : '- ') + line).join('\n');
  return { value: value.slice(0, start) + insert + value.slice(end), start, end: start + insert.length };
}
