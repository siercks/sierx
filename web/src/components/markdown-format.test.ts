import { expect, test } from 'vitest';
import { formatMarkdown } from './markdown-format';
test('formatting preserves surrounding draft and selects its editable text', () => {
  expect(formatMarkdown('before hello after', 7, 12, 'bold')).toEqual({ value: 'before **hello** after', start: 9, end: 14 });
  const link = formatMarkdown('name', 0, 4, 'link');
  expect(link.value.slice(link.start, link.end)).toBe('https://example.com');
});
test('list formatting starts at the current line and keeps later content', () => {
  expect(formatMarkdown('first\none\ntwo\nlast', 8, 13, 'numbers').value).toBe('first\n1. one\n2. two\nlast');
});
