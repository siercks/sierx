import MarkdownIt from 'markdown-it';
export const markdown = new MarkdownIt({
  html: false,
  linkify: true,
  typographer: false,
  breaks: false,
});
markdown.validateLink = (url) => /^(https?:|mailto:)/i.test(url);
markdown.renderer.rules.link_open = (tokens, index, options, _env, self) => {
  tokens[index].attrSet('rel', 'noopener noreferrer');
  tokens[index].attrSet('target', '_blank');
  return self.renderToken(tokens, index, options);
};
// External images leak reading activity; render their alt text as an ordinary
// safe link instead. Uploading attachments is outside Phase 2.
markdown.renderer.rules.image = (tokens, index) => {
  const token = tokens[index],
    src = String(token.attrGet('src') ?? ''),
    alt = markdown.utils.escapeHtml(token.content || 'Image');
  return markdown.validateLink(src)
    ? `<a href="${markdown.utils.escapeHtml(src)}" rel="noopener noreferrer" target="_blank">${alt}</a>`
    : alt;
};
export const renderMarkdown = (text: string) => markdown.render(text);
