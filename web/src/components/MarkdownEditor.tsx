import { lazy, Suspense, useEffect, useId, useRef, useState } from 'react';
import { Button } from './ui/button';
import { formatMarkdown, type Format } from './markdown-format';
const Preview = lazy(() => import('./MarkdownPreview'));
const formats: [Format, string][] = [['bold', 'Bold'], ['italic', 'Italic'], ['heading', 'Heading'], ['bullets', 'Bulleted list'], ['numbers', 'Numbered list'], ['link', 'Link'], ['quote', 'Quote'], ['code', 'Code']];

export function MarkdownEditor({ label, name, defaultValue = '', required = false, placeholder }: {
  label: string; name: string; defaultValue?: string; required?: boolean; placeholder?: string;
}) {
  const id = useId();
  const ref = useRef<HTMLTextAreaElement>(null);
  const [value, setValue] = useState(defaultValue);
  const [preview, setPreview] = useState(false);
  useEffect(() => {
    const form = ref.current?.form;
    const reset = () => { setValue(defaultValue); setPreview(false); };
    form?.addEventListener('reset', reset);
    return () => form?.removeEventListener('reset', reset);
  }, [defaultValue]);
  function apply(format: Format) {
    const input = ref.current!;
    const next = formatMarkdown(value, input.selectionStart, input.selectionEnd, format);
    setValue(next.value); setPreview(false);
    input.dispatchEvent(new Event('input', { bubbles: true }));
    requestAnimationFrame(() => { input.focus(); input.setSelectionRange(next.start, next.end); });
  }
  return <div className="workflow-field workflow-field-full">
    <label htmlFor={id}>{label}</label>
    <div className="toolbar" role="group" aria-label={`${label} formatting`}>
      {formats.map(([format, text]) => <Button key={format} type="button" variant="ghost" size="sm" onClick={() => apply(format)}>{text}</Button>)}
      <Button type="button" variant="outline" size="sm" aria-pressed={preview} aria-controls={`${id}-preview`} onClick={() => setPreview(!preview)}>Preview</Button>
    </div>
    <textarea ref={ref} id={id} className="sx-control" name={name} required={required} value={value} placeholder={placeholder} onChange={(event) => setValue(event.target.value)} onKeyDown={(event) => {
      if ((event.ctrlKey || event.metaKey) && ['b', 'i'].includes(event.key.toLowerCase())) {
        event.preventDefault(); apply(event.key.toLowerCase() === 'b' ? 'bold' : 'italic');
      }
    }} />
    {preview && <section id={`${id}-preview`} className="card" aria-label={`${label} preview`}><Suspense fallback={<p role="status">Loading preview…</p>}><Preview text={value} /></Suspense></section>}
  </div>;
}
