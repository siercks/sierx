import { renderMarkdown } from '../markdown/render';
export default function MarkdownPreview({ text }: { text: string }) {
  return <div className="sx-md markdown" dangerouslySetInnerHTML={{ __html: renderMarkdown(text) }} />;
}
