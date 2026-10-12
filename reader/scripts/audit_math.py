#!/usr/bin/env python3
"""Read-only audit of published Reader article math; never rewrite source text.

Scan the built site (not historical backups). Optionally typeset each article's
formulas in the local MathJax build. Results are candidates, not semantic proofs.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from dataclasses import dataclass, field
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sqlite3
import zlib

READER = Path(__file__).resolve().parents[1]
VOID = set('area base br col embed hr img input link meta param source track wbr'.split())
TEX = re.compile(r'\\(?:frac|dfrac|tfrac|sum|prod|int|sqrt|alpha|beta|gamma|theta|pi|sigma|ell|nabla|mathbb|mathcal|mathrm|operatorname|begin)\b')
MATH_NAME = re.compile(r'\b(?:pi_(?:theta|old|ref|SFT)|ell_(?:it|old|ref)|sigma_R|epsilon_[lh]|grad_theta|mean_(?:group|G))\b|\b[A-Za-z]_(?:i[,_]?t|i|t|j|LOO)\b')
MATH_SYMBOL = re.compile(r'[∑∏∫√∇πθσβρℓε]|[A-Za-z}]\s*\^\s*[{(\d-]')
EQUATION = re.compile(r'(?<![<>=!])=(?!=)|[<>≤≥≈]|(?:\+|−|\*|/)')
CODE = re.compile(r'\b(?:torch|np|numpy|self|model|loss|logits|tensor)\.|\b(?:def|return|import|for|if|else|None|True|False)\b|\.\w+\(|(?:https?://)|(?:--[a-z][\w-]*)|(?:\.py|\.json|\.yaml|\.yml)\b')

@dataclass
class Node:
    tag: str
    attrs: dict = field(default_factory=dict)
    children: list = field(default_factory=list)
    parent: Node | None = None

    def text(self):
        return ''.join(c if isinstance(c, str) else c.text() for c in self.children)

    def walk(self):
        yield self
        for child in self.children:
            if isinstance(child, Node):
                yield from child.walk()

    def inside(self, tag):
        parent = self.parent
        while parent:
            if parent.tag == tag:
                return True
            parent = parent.parent
        return False

    def has_class(self, name):
        return name in self.attrs.get('class', '').split()

class Document(HTMLParser):
    def __init__(self, source):
        super().__init__(convert_charrefs=True)
        self.root = Node('root')
        self.stack = [self.root]
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        node = Node(tag, dict(attrs), parent=self.stack[-1])
        self.stack[-1].children.append(node)
        if tag not in VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def classify_code(value):
    value = value.strip()
    if TEX.search(value):
        return 'high', '代码格式中含 LaTeX 数学命令'
    if CODE.search(value) or len(value) > 400 or '->' in value or '→' in value:
        return None
    if re.search(r'\b(?:batch|shape|dtype)\s*=', value):
        return None
    if (MATH_NAME.search(value) or MATH_SYMBOL.search(value)) and EQUATION.search(value):
        return 'high', '代码格式中含数学符号/下标及运算关系'
    if MATH_NAME.fullmatch(value) or MATH_SYMBOL.search(value):
        return 'review', '疑似数学变量或数学符号，也可能是程序记号'
    if re.search(r'\b(?:log|exp|sqrt|KL|softmax|sigmoid)\s*\(', value) and EQUATION.search(value):
        return 'review', '疑似数学函数表达式，也可能是伪代码'
    if re.search(r'^\s*[A-Za-z](?:_[A-Za-z0-9]+)?\s*=', value) and re.search(r'[+*/−]|\b(?:log|sum|mean)\b', value):
        return 'review', '疑似公式赋值，也可能是代码示例'
    return None


def prose(node):
    if node.tag in {'code', 'pre', 'script', 'style'} or node.has_class('arithmatex'):
        return ''
    return ''.join(c if isinstance(c, str) else prose(c) for c in node.children)


def scan(database, task_dir):
    findings, pages, formulas = [], [], []
    counts = Counter()
    source_cache = {}
    with sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True) as db:
        rows = db.execute("SELECT path, content, compression FROM files WHERE path LIKE '%.html' AND content IS NOT NULL ORDER BY path").fetchall()
    for path, content, compression in rows:
        counts['html_files'] += 1
        source = (zlib.decompress(content) if compression == 'zlib' else content).decode('utf-8')
        doc = Document(source)
        article = next((n for n in doc.root.walk() if n.tag == 'article' and n.has_class('md-content__inner')), None)
        if article is None:
            continue
        nodes = list(article.walk())
        meta = next((n for n in nodes if n.has_class('reader-document-meta')), None)
        document_id = meta.attrs.get('data-document-id', '') if meta else ''
        page = {'page': path, 'document_id': document_id}
        pages.append(page)
        counts['articles'] += 1
        kind = path.split('/')[0] if '/' in path else 'root'
        counts['articles_' + kind] += 1
        heading = ''
        for node in nodes:
            if node.tag in {'h1', 'h2', 'h3', 'h4'}:
                heading = node.text().rstrip('¶')
            if node.has_class('arithmatex'):
                formulas.append({**page, 'heading': heading, 'tex': node.text()})
                counts['formulas'] += 1
            if node.tag != 'code' or node.inside('pre'):
                continue
            counts['inline_code'] += 1
            candidate = classify_code(node.text())
            if not candidate:
                continue
            level, reason = candidate
            item = {**page, 'heading': heading, 'level': level, 'kind': 'math_in_code', 'text': node.text(), 'reason': reason}
            if document_id:
                source_path = task_dir / ('REPORT.md' if document_id == 'report/index.md' else document_id)
                if source_path.is_file():
                    if source_path not in source_cache:
                        source_cache[source_path] = source_path.read_text().splitlines()
                    matches = [i for i, line in enumerate(source_cache[source_path], 1) if '`' + node.text() + '`' in line]
                    if matches:
                        item.update(source=str(source_path.resolve()), lines=matches)
            findings.append(item)
        # Only leaf prose blocks: avoid counting nested list/table paragraphs twice.
        for node in nodes:
            if node.tag not in {'p', 'li', 'td', 'th'}:
                continue
            if any(child is not node and child.tag in {'p', 'li', 'td', 'th'} for child in node.walk()):
                continue
            value = prose(node)
            if TEX.search(value) or re.search(r'\$\$|\\[\[\]()]', value):
                findings.append({**page, 'level': 'review', 'kind': 'raw_math_marker', 'text': value.strip()[:500], 'reason': 'Markdown 未生成公式节点；MathJax 首屏可能仍能渲染，不能直接认定为显示错误'})
    return {'summary': dict(counts), 'findings': findings, 'pages': pages, 'formulas': formulas}


async def render_check(formulas, base_url, executable):
    from playwright.async_api import async_playwright
    errors = []
    grouped = {}
    for item in formulas:
        grouped.setdefault(item['page'], []).append(item)
    async with async_playwright() as p:
        kwargs = {'headless': True}
        if executable:
            kwargs['executable_path'] = executable
        browser = await p.chromium.launch(**kwargs)
        page = await browser.new_page()
        # No Reader application JS, network APIs, or saved reading positions.
        await page.goto(base_url + '/stylesheets/extra.css')
        await page.set_content('<html><body><article></article></body></html>')
        await page.add_script_tag(url=base_url + '/javascripts/mathjax.js')
        await page.add_script_tag(url=base_url + '/vendor/mathjax/tex-mml-chtml.js')
        await page.evaluate('MathJax.startup.promise')
        for index, (path, items) in enumerate(grouped.items(), 1):
            result = await page.evaluate('''async items => {
                MathJax.typesetClear();
                MathJax.texReset();
                const article = document.querySelector('article');
                article.replaceChildren();
                const nodes = items.map(item => {
                    const node = document.createElement(item.tex.startsWith('\\\\[') ? 'div' : 'span');
                    node.className = 'arithmatex';
                    node.textContent = item.tex;
                    article.append(node);
                    return node;
                });
                await MathJax.typesetPromise(nodes);
                return nodes.flatMap((node, i) => {
                    const error = node.querySelector('mjx-merror, [data-mjx-error]');
                    if (error) return [{index:i, error:error.getAttribute('data-mjx-error') || error.textContent}];
                    if (!node.querySelector('mjx-container')) return [{index:i, error:'未生成公式节点'}];
                    return [];
                });
            }''', items)
            for error in result:
                errors.append({**items[error['index']], 'error': error['error']})
            if index % 20 == 0:
                print(f'Rendered {index}/{len(grouped)} articles', flush=True)
        await browser.close()
    return {'status': 'complete', 'articles': len(grouped), 'formulas': len(formulas), 'errors': errors}


def write_report(result, output):
    output.mkdir(parents=True, exist_ok=True)
    (output / 'math-audit.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    counts = Counter(f['level'] for f in result['findings'])
    lines = ['# 正文公式自动检查', '', '范围：当前已构建站点中的全部正文 HTML；排除导航、历史备份和代码块。不会修改原文。', '',
             '局限：候选项不等于错误；伪代码与数学表达式有重叠。不会检查数学推导正确性，不扫描 PDF、图片或独立存储的译文/聊天记录。未配对的单个美元符号不能可靠地区分公式与金额，本检查不保证检出。', '',
             '## 统计', '', '```json', json.dumps(result['summary'], ensure_ascii=False, indent=2), '```', '',
             f"高置信候选 {counts['high']} 处；需复核候选 {counts['review']} 处。", '']
    lines += ['## 候选最多的正文文档', '', '| 文档 | 高置信候选 | 需复核 |', '|---|---:|---:|']
    by_page = {}
    for finding in result['findings']:
        key = finding.get('document_id') or finding['page']
        by_page.setdefault(key, Counter())[finding['level']] += 1
    for path, counts in sorted(by_page.items(), key=lambda item: (-item[1]['high'], -item[1]['review'], item[0]))[:15]:
        lines.append(f"| {path} | {counts['high']} | {counts['review']} |")
    lines += ['', '## 渲染检查', '']
    render = result.get('render', {})
    lines += [f"MathJax 检查：{render.get('status', '未运行')}；检查 {render.get('formulas', 0)} 个已标记公式，错误 {len(render.get('errors', []))} 处。", '']
    if result.get('raw_marker_verification'):
        lines += [result['raw_marker_verification'], '']
    for error in render.get('errors', []):
        lines += [f"- `{error['page']}`：{error['error']}", '', '```text', error['tex'], '```', '']
    for level, title in [('high', '高置信候选（仍需确认语境）'), ('review', '需复核候选')]:
        lines += ['## ' + title, '']
        for finding in result['findings']:
            if finding['level'] != level:
                continue
            location = finding.get('document_id') or finding['page']
            if finding.get('lines'):
                location += ':' + ','.join(map(str, finding['lines']))
            lines += [f"- **{location}** — {finding['reason']}", '', '```text', finding['text'], '```', '']
    (output / 'math-audit.md').write_text('\n'.join(lines))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--task-id', default='paper-research-base-knowledge-about-llm-20260717')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--render', action='store_true')
    parser.add_argument('--base-url', default='http://127.0.0.1:8000')
    parser.add_argument('--browser', default='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')
    args = parser.parse_args()
    database = READER / 'user-data' / args.task_id / 'site.sqlite3'
    result = scan(database, READER.parent / 'tasks' / args.task_id)
    print(json.dumps(result['summary'], ensure_ascii=False), flush=True)
    print('Candidates:', dict(Counter(f['level'] for f in result['findings'])), flush=True)
    write_report(result, args.output)
    if args.render:
        result['render'] = asyncio.run(render_check(result['formulas'], args.base_url.rstrip('/'), args.browser))
        write_report(result, args.output)
        print('MathJax errors:', len(result['render']['errors']), flush=True)
    print('Report:', args.output.resolve() / 'math-audit.md', flush=True)

if __name__ == '__main__':
    main()
