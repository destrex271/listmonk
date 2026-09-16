import { readFileSync, writeFileSync } from 'node:fs';
import { TEditorConfiguration } from './src/documents/editor/core';
import { renderHtmlWithMeta } from './src/utils';

const inputPath = process.argv[2];
const outputPath = process.argv[3];

if (!inputPath) {
  console.error('Usage: node render-cli.js <input.json> [output.html]');
  process.exit(1);
}

const document = JSON.parse(readFileSync(inputPath, 'utf8')) as TEditorConfiguration;
const outlook = Boolean((document.root as { data?: { outlook?: boolean } })?.data?.outlook);
const html = renderHtmlWithMeta(document, { rootBlockId: 'root', outlook });

if (outputPath) {
  writeFileSync(outputPath, html, 'utf8');
  console.error(`Wrote ${html.length} bytes to ${outputPath}`);
} else {
  process.stdout.write(html + '\n');
}