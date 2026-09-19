import { it, expect } from 'vitest';
import { parseHTML } from 'linkedom';
import { renderMarkdown } from './render';
const hostile = [
  '<script>alert(1)</script>',
  '<img src=x onerror=alert(1)>',
  '<iframe src="https://example.test"></iframe>',
  '[bad](javascript:alert(1))',
  '[bad](data:text/html,evil)',
  '<style>body{display:none}</style>',
  '<!-- secret -->',
  '[bad](jav&#x61;script:alert(1))',
  '[bad](vbscript:evil)',
  '![bad](data:image/svg+xml,evil)',
];
const allowed = new Set([
  'P',
  'A',
  'UL',
  'OL',
  'LI',
  'STRONG',
  'EM',
  'CODE',
  'PRE',
  'BLOCKQUOTE',
  'H1',
  'H2',
  'H3',
  'H4',
  'H5',
  'H6',
  'HR',
  'BR',
  'S',
]);
function auditHTML(html: string) {
  const { document: doc } = parseHTML('<html><body>' + html + '</body></html>');
  for (const element of doc.body.querySelectorAll('*')) {
    expect(allowed.has(element.tagName)).toBe(true);
    for (const a of element.attributes) {
      expect(a.name).not.toMatch(/^on|^style$/i);
      if (a.name === 'href') expect(a.value).toMatch(/^(https?:|mailto:)/i);
    }
  }
}
it('hostile corpus cannot create active elements, event handlers or unsafe links', () => {
  for (const input of hostile) auditHTML(renderMarkdown(input));
});
it('rejects a deliberately unsafe renderer', () => {
  expect(() => auditHTML('<script>alert(1)</script>')).toThrow();
  expect(() => auditHTML('<a href="javascript:alert(1)">bad</a>')).toThrow();
  expect(() => auditHTML('<p onclick="alert(1)">bad</p>')).toThrow();
});
it('external links have isolation attributes and Markdown remains usable', () => {
  const { document: doc } = parseHTML(
    renderMarkdown('**Strong** [link](https://example.test)'),
  );
  expect(doc.querySelector('strong')?.textContent).toBe('Strong');
  expect(doc.querySelector('a')?.getAttribute('rel')).toBe(
    'noopener noreferrer',
  );
  expect(doc.querySelector('a')?.getAttribute('target')).toBe('_blank');
});
