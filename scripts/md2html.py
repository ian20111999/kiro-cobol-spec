#!/usr/bin/env python3
"""Simple Markdown to HTML converter with CSS styling."""
import argparse
import re
import sys
import os

def md_to_html(md_text):
    lines = md_text.split('\n')
    html_lines = []
    in_table = False
    in_code = False
    in_ul = False
    in_ol = False
    code_lang = ''

    i = 0
    while i < len(lines):
        line = lines[i]

        # Code blocks
        if line.strip().startswith('```'):
            if not in_code:
                in_code = True
                code_lang = line.strip()[3:]
                html_lines.append(f'<pre><code class="language-{code_lang}">')
            else:
                in_code = False
                html_lines.append('</code></pre>')
            i += 1
            continue

        if in_code:
            html_lines.append(escape_html(line))
            i += 1
            continue

        # Close lists if needed
        if in_ul and not line.strip().startswith('- ') and not line.strip().startswith('  '):
            html_lines.append('</ul>')
            in_ul = False
        if in_ol and not re.match(r'^\d+\.', line.strip()) and not line.strip().startswith('  '):
            html_lines.append('</ol>')
            in_ol = False

        # Table
        if '|' in line and line.strip().startswith('|'):
            cells = [c.strip() for c in line.strip().split('|')[1:-1]]
            if all(re.match(r'^[-:]+$', c) for c in cells):
                # separator row - skip
                i += 1
                continue
            if not in_table:
                in_table = True
                html_lines.append('<table>')
                # Check if next line is separator (this is header)
                if i + 1 < len(lines) and re.match(r'^\|[-|: ]+\|$', lines[i+1].strip()):
                    html_lines.append('<thead><tr>')
                    for c in cells:
                        html_lines.append(f'<th>{inline_format(c)}</th>')
                    html_lines.append('</tr></thead><tbody>')
                    i += 2  # skip separator
                    continue
                else:
                    html_lines.append('<tbody>')
            html_lines.append('<tr>')
            for c in cells:
                html_lines.append(f'<td>{inline_format(c)}</td>')
            html_lines.append('</tr>')
            i += 1
            continue
        elif in_table:
            html_lines.append('</tbody></table>')
            in_table = False

        stripped = line.strip()

        # Empty line
        if not stripped:
            html_lines.append('')
            i += 1
            continue

        # Horizontal rule
        if stripped in ('---', '***', '___'):
            html_lines.append('<hr>')
            i += 1
            continue

        # Headings
        m = re.match(r'^(#{1,6})\s+(.*)', line)
        if m:
            level = len(m.group(1))
            text = m.group(2)
            html_lines.append(f'<h{level}>{inline_format(text)}</h{level}>')
            i += 1
            continue

        # Unordered list
        if stripped.startswith('- '):
            if not in_ul:
                in_ul = True
                html_lines.append('<ul>')
            html_lines.append(f'<li>{inline_format(stripped[2:])}</li>')
            i += 1
            continue

        # Ordered list
        m = re.match(r'^(\d+)\.\s+(.*)', stripped)
        if m:
            if not in_ol:
                in_ol = True
                html_lines.append('<ol>')
            html_lines.append(f'<li>{inline_format(m.group(2))}</li>')
            i += 1
            continue

        # Paragraph
        html_lines.append(f'<p>{inline_format(stripped)}</p>')
        i += 1

    # Close any open elements
    if in_table:
        html_lines.append('</tbody></table>')
    if in_ul:
        html_lines.append('</ul>')
    if in_ol:
        html_lines.append('</ol>')
    if in_code:
        html_lines.append('</code></pre>')

    return '\n'.join(html_lines)

def escape_html(text):
    return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

def inline_format(text):
    text = escape_html(text)
    # Bold
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    # Italic
    text = re.sub(r'\*(.+?)\*', r'<em>\1</em>', text)
    # Code
    text = re.sub(r'`(.+?)`', r'<code>\1</code>', text)
    return text

def extract_title(md_text):
    """Extract the title from the first H1 heading in the markdown content."""
    m = re.search(r'^#\s+(.+)$', md_text, re.MULTILINE)
    if m:
        return m.group(1).strip()
    return 'COBOL Spec'

CSS = """
body {
    font-family: "Microsoft JhengHei", "PingFang TC", "Noto Sans TC", sans-serif;
    max-width: 1200px;
    margin: 0 auto;
    padding: 20px 40px;
    line-height: 1.6;
    color: #333;
    background: #fff;
}
h1 {
    color: #1a365d;
    border-bottom: 3px solid #2c5282;
    padding-bottom: 10px;
    font-size: 1.8em;
}
h2 {
    color: #2c5282;
    border-bottom: 2px solid #bee3f8;
    padding-bottom: 6px;
    margin-top: 2em;
    font-size: 1.4em;
}
h3 {
    color: #2b6cb0;
    margin-top: 1.5em;
    font-size: 1.2em;
}
h4 {
    color: #3182ce;
    margin-top: 1.2em;
}
table {
    border-collapse: collapse;
    width: 100%;
    margin: 1em 0;
    font-size: 0.9em;
}
th, td {
    border: 1px solid #cbd5e0;
    padding: 8px 12px;
    text-align: left;
}
th {
    background-color: #ebf8ff;
    font-weight: bold;
    color: #2c5282;
}
tr:nth-child(even) {
    background-color: #f7fafc;
}
tr:hover {
    background-color: #edf2f7;
}
pre {
    background-color: #f7fafc;
    border: 1px solid #e2e8f0;
    border-radius: 4px;
    padding: 16px;
    overflow-x: auto;
    font-size: 0.85em;
    line-height: 1.4;
}
code {
    background-color: #edf2f7;
    padding: 2px 6px;
    border-radius: 3px;
    font-family: "Courier New", Consolas, monospace;
    font-size: 0.9em;
}
pre code {
    background: none;
    padding: 0;
}
hr {
    border: none;
    border-top: 2px solid #e2e8f0;
    margin: 2em 0;
}
p {
    margin: 0.5em 0;
}
ul, ol {
    margin: 0.5em 0;
    padding-left: 2em;
}
li {
    margin: 0.3em 0;
}
strong {
    color: #1a365d;
}
em {
    color: #4a5568;
}
@media print {
    body { max-width: none; padding: 10px; }
    table { page-break-inside: avoid; }
    h2 { page-break-before: auto; }
    pre { white-space: pre-wrap; }
}
"""

def main():
    parser = argparse.ArgumentParser(
        description="Convert Markdown spec to styled HTML with CJK-friendly CSS."
    )
    parser.add_argument(
        "input",
        help="Path to the input Markdown file.",
    )
    parser.add_argument(
        "output",
        nargs="?",
        default=None,
        help="Path to the output HTML file (default: input with .html extension).",
    )
    args = parser.parse_args()

    input_file = args.input
    if args.output:
        output_file = args.output
    else:
        base, _ = os.path.splitext(input_file)
        output_file = base + '.html'

    with open(input_file, 'r', encoding='utf-8', errors='replace') as f:
        md_text = f.read()

    title = extract_title(md_text)
    body = md_to_html(md_text)

    html = f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{escape_html(title)}</title>
<style>
{CSS}
</style>
</head>
<body>
{body}
</body>
</html>"""

    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f"Generated {output_file}")

if __name__ == '__main__':
    main()
