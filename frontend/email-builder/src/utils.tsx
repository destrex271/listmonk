import { renderToStaticMarkup } from '@usewaypoint/email-builder';
import { TEditorConfiguration } from './documents/editor/core';
import { postProcessForOutlook } from './outlook';

const VIEWPORT_META = '<meta name="viewport" content="width=device-width, initial-scale=1.0">';
const MSO_DOCUMENT_SETTINGS = '<!--[if mso]><noscript><xml xmlns:o="urn:schemas-microsoft-com:office:office"><o:OfficeDocumentSettings><o:AllowPNG/><o:PixelsPerInch>96</o:PixelsPerInch></o:OfficeDocumentSettings></xml></noscript><![endif]-->';
const HTML_ATTRIBUTE_ESCAPES: Record<string, string> = {
  '&': '&amp;',
  '"': '&quot;',
  "'": '&#x27;',
  '<': '&lt;',
  '>': '&gt;',
};

// Responsive media query for ColumnsContainer. The base block renders its
// cells as inline-styled <td>s (side by side on all screens); this rule stacks
// them into full-width rows on mobile, like the hybrid email technique.
const HYBRID_STACK_CSS = `
  <style>
    @media only screen and (max-width: 600px) {
      .lm-col { display: block !important; width: 100% !important; }
    }
  </style>`;

// The base ColumnsContainer cell <td> always carries an inline
// `box-sizing: content-box` style, which is unique to those cells in the
// rendered document. Mark them with a class so the media query can target them.
function markResponsiveColumns(html: string): string {
  return html.replace(
    /<td style="box-sizing: content-box;/g,
    '<td class="lm-col" style="box-sizing: content-box;',
  );
}

function injectHeadContents(html: string, contents: string) {
  const headMatch = html.match(/<head\b([^>]*)>/i);
  if (headMatch) {
    return html.replace(/<head\b([^>]*)>/i, `<head$1>${contents}`);
  }

  const htmlMatch = html.match(/<html\b([^>]*)>/i);
  if (htmlMatch) {
    return html.replace(/<html\b([^>]*)>/i, `<html$1><head>${contents}</head>`);
  }

  return `<head>${contents}</head>${html}`;
}

function collectImageEmbedURLs(document: TEditorConfiguration): string[] {
  // The upstream renderer strips the custom `embed` prop before rendering, so
  // collect URLs from blocks marked for embedding and re-tag the matching <img>
  // with a `data-embed` flag after rendering. The backend resolves the src
  // filename to a media item at compile time.
  const embedURLs: string[] = [];

  for (const block of Object.values(document)) {
    if (!block || (block as { type?: string }).type !== 'Image') {
      continue;
    }

    const props = ((block as { data?: { props?: { url?: string; embed?: boolean } } }).data || {}).props || {};
    if (props.embed && props.url) {
      embedURLs.push(props.url);
    }
  }

  return embedURLs;
}

function applyImageEmbeds(html: string, embedURLs: string[]): string {
  let output = html;

  for (const url of embedURLs) {
    const re = new RegExp(`<img\\b[^>]*?\\ssrc="${escapeRegExp(escapeHtmlAttribute(url))}"[^>]*>`, 'g');
    output = output.replace(re, (tag) => (
      /\bdata-embed\b/.test(tag) ? tag : tag.replace(/(\ssrc="[^"]*")/, '$1 data-embed="true"')
    ));
  }

  return output;
}

export function renderHtmlWithMeta(
  document: TEditorConfiguration,
  options: { rootBlockId: string; outlook?: boolean }
): string {
  const embedURLs = collectImageEmbedURLs(document);
  const html = renderToStaticMarkup(document, options);
  const rendered = options.outlook ? postProcessForOutlook(html) : html;
  const output = applyImageEmbeds(markResponsiveColumns(rendered), embedURLs);
  const head = options.outlook ? `${VIEWPORT_META}${MSO_DOCUMENT_SETTINGS}` : VIEWPORT_META;

  return injectHeadContents(output, head + HYBRID_STACK_CSS);
}

function escapeRegExp(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function escapeHtmlAttribute(s: string): string {
  return s.replace(/[&"'<>]/g, (ch) => HTML_ATTRIBUTE_ESCAPES[ch]);
}
