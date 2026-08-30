#!/usr/bin/env python3
"""Convert ColumnsContainer blocks in an email-builder JSON into stacked Columns.

Each ColumnsContainer block (which renders its cells side-by-side in a table
row) is replaced by a vertically-stacking Container block whose children are
the two/three columns' blocks flattened in order. This yields a one-column
layout that renders stacked at every viewport in every email client.

Usage:
  python3 convert_stacked_columns.py <input.json> [-o <output.json>] [--sanitize]
      [--render <out.html>]

  input.json    Source waypoint/email-builder document.
  -o <file>     Write result to <file> (default: overwrite the input file,
                after making a <file>.bak copy).
  --sanitize    Also repair malformed Html block fragments (drop orphan
                closing tags, auto-close open ones).
  --no-convert  Skip column conversion; only apply --sanitize. Use this to
                keep 2-column sections responsive (stacked on mobile via the
                renderer's media query, side-by-side on desktop).
  --render      Also render the resulting document to a final HTML file via
                the email-builder's render CLI (bundled once into
                scripts/.render/), then inject the canonical mobile CSS
                (MOBILE_PADDING_CSS) into the document <head>.
"""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

VOID_TAGS = {
    'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input',
    'link', 'meta', 'param', 'source', 'track', 'wbr',
}

# Matches HTML comments, conditional comments, declarations, closing tags and
# opening/self-closing tags. Group 2 = closing tag name, group 3 = opening tag
# name; the full match is the raw token text.
TAG_RE = re.compile(
    r'(<!--.*?--\s*>|<!\s*\[endif\]\s*-->|<!\[[^>]*\]>|<!DOCTYPE[^>]*>|'
    r'</\s*([a-zA-Z][a-zA-Z0-9]*)\s*>|'
    r'<\s*([a-zA-Z][a-zA-Z0-9]*)(?:\s[^<>]*?)?\s*/?>)',
    re.DOTALL | re.IGNORECASE,
)


def repair_fragment(fragment: str) -> str:
    """Rebalance a pasted HTML fragment.

    Drops closing tags with no matching opener, closes any tags opened before
    an enclosing tag closes (in correct nesting order), and appends closing
    tags for whatever is still open at the end. The original text is preserved
    verbatim otherwise.
    """
    out: list[str] = []
    stack: list[str] = []
    pos = 0

    for match in TAG_RE.finditer(fragment):
        raw = match.group(0)
        if pos < match.start():
            out.append(fragment[pos:match.start()])
        pos = match.end()

        if raw.startswith('<!--') or raw.startswith('<!'):
            out.append(raw)
            continue

        if raw.startswith('</'):
            name = (match.group(2) or '').lower()
            if name in VOID_TAGS:
                out.append(raw)
            elif name in stack:
                while stack and stack[-1] != name:
                    out.append(f'</{stack.pop()}>')
                stack.pop()
                out.append(raw)
            continue

        name = (match.group(3) or '').lower()
        if name in VOID_TAGS or raw.rstrip().endswith('/>'):
            out.append(raw)
            continue
        stack.append(name)
        out.append(raw)

    if pos < len(fragment):
        out.append(fragment[pos:])
    while stack:
        out.append(f'</{stack.pop()}>')

    return ''.join(out)


def sanitize_document(document: dict) -> int:
    fixed = 0
    for block in document.values():
        if not isinstance(block, dict) or block.get('type') != 'Html':
            continue
        props = (block.get('data') or {}).get('props') or {}
        contents = props.get('contents')
        if not isinstance(contents, str):
            continue
        repaired = repair_fragment(contents)
        if repaired != contents:
            props['contents'] = repaired
            fixed += 1
    return fixed


def convert_columns(document: dict) -> list[str]:
    """Replace every ColumnsContainer with a stacked Container.

    Returns the list of ids that were converted.
    """
    converted = []
    for block_id, block in document.items():
        if not isinstance(block, dict) or block.get('type') != 'ColumnsContainer':
            continue
        data = block.get('data') or {}
        props = data.get('props') or {}
        columns = props.get('columns') or []

        children = []
        for column in columns:
            if not isinstance(column, dict):
                continue
            children.extend(column.get('childrenIds') or [])

        document[block_id] = {
            'type': 'Container',
            'data': {
                'style': data.get('style'),
                'props': {'childrenIds': children},
            },
        }
        converted.append((block_id, len(children)))

    return [(cid, count) for cid, count in converted]


# Canonical mobile-only CSS applied to the final rendered email: stacks
# ColumnsContainer cells (marked with class "lm-col") into rows on narrow
# screens. The single source of truth for this rule is this Python script; the
# listmonk delivery layer mirrors it in internal/manager/postprocess.go
# (lmColCSS). No padding/spacing overrides are applied — the columns'
# embedded layout is preserved as authored.
STACK_COLUMNS_CSS = """@media only screen and (max-width: 600px) {
  .lm-col { display: block !important; width: 100% !important; }
}
"""

# Matches whole <style> blocks that carry the builder's mobile stacking rule so
# they can be replaced by the canonical STACK_COLUMNS_CSS (which already
# includes the .lm-col rule) rather than duplicated.
_LM_STYLE_RE = re.compile(r'(?is)<style(?:\s[^>]*)?>[\s\S]*?\.lm-col[\s\S]*?</style>')
_HEAD_CLOSE_RE = re.compile(r'(?i)</head\s*>')


def inject_final_css(html: str) -> str:
    """Swap in the canonical mobile CSS and guarantee the viewport meta."""
    html = _LM_STYLE_RE.sub('', html)
    style_block = f'<style>\n{STACK_COLUMNS_CSS.strip()}\n</style>'
    contents = style_block + '\n'
    if 'width=device-width, initial-scale=1.0' not in html:
        contents = '<meta name="viewport" content="width=device-width, initial-scale=1.0">\n' + contents
    if _HEAD_CLOSE_RE.search(html):
        return _HEAD_CLOSE_RE.sub(contents + '</head>', html, count=1)
    return html + '\n' + contents


def _render_cli_bundle(repo_root: Path) -> Path:
    """Locate the bundled render CLI, building it once if missing/stale."""
    bundle = repo_root / 'scripts' / '.render' / 'render-cli.cjs'
    source = repo_root / 'frontend' / 'email-builder' / 'render-cli.ts'
    builder = repo_root / 'frontend' / 'email-builder'
    esbuild = builder / 'node_modules' / '.bin' / 'esbuild'
    stale = not bundle.exists() or source.stat().st_mtime > bundle.stat().st_mtime
    if not stale:
        return bundle
    if not esbuild.exists():
        sys.exit('error: esbuild not found; run `make build-email-builder` first')
    bundle.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [os.fspath(esbuild), 'render-cli.ts', '--bundle', '--platform=node',
         '--format=cjs', f'--outfile={bundle}'],
        cwd=builder, check=True)
    return bundle


def render_html(input_json: str, output_html: str) -> None:
    """Render a (converted) document JSON to final mobile-ready HTML."""
    repo_root = Path(__file__).resolve().parents[1]
    bundle = _render_cli_bundle(repo_root)
    result = subprocess.run(
        ['node', os.fspath(bundle), input_json],
        capture_output=True, text=True, check=True)
    html = result.stdout
    if not html.strip().lower().startswith('<!doctype') and '<html' not in html[:200]:
        sys.exit(f'error: render CLI produced no HTML:\n{result.stderr}')
    html = inject_final_css(html)
    with open(output_html, 'w', encoding='utf-8') as fh:
        fh.write(html)
    print(f'[render] wrote {output_html} ({len(html)} bytes)')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('input', help='Source email-builder JSON document')
    parser.add_argument('-o', '--output', help='Output file (default: overwrite input)')
    parser.add_argument('--sanitize', action='store_true', help='Also repair malformed Html fragments')
    parser.add_argument('--no-convert', action='store_true', help='Keep columns responsive; only sanitize if requested')
    parser.add_argument('--render', metavar='<out.html>', help='Also render the result to final HTML with canonical mobile CSS')
    args = parser.parse_args()

    input_path = args.input
    output_path = args.output or input_path

    try:
        with open(input_path, encoding='utf-8') as fh:
            source_text = fh.read()
    except FileNotFoundError:
        sys.exit(f'error: file not found: {input_path}')

    document = json.loads(source_text)
    if not isinstance(document, dict):
        sys.exit('error: expected a JSON object (a document map of blocks)')

    if args.sanitize:
        fixed = sanitize_document(document)
        print(f'[sanitize] repaired {fixed} Html block(s)')

    converted = [] if args.no_convert else convert_columns(document)
    if not converted:
        print('[convert] no ColumnsContainer blocks found; nothing to do')
    else:
        for block_id, count in converted:
            print(f'[convert] {block_id}: ColumnsContainer -> Container ({count} child block(s), stacked)')

    if output_path == input_path:
        backup = f'{input_path}.bak'
        with open(backup, 'w', encoding='utf-8') as fh:
            fh.write(source_text)
        print(f'[backup] wrote {backup}')

    text = json.dumps(document, ensure_ascii=False, indent=2)
    # Preserve the input's trailing-newline convention.
    if source_text.endswith('\n') and not text.endswith('\n'):
        text += '\n'
    with open(output_path, 'w', encoding='utf-8') as fh:
        fh.write(text)

    print(f'[done] wrote {output_path}')

    if args.render:
        render_html(output_path, args.render)


if __name__ == '__main__':
    main()