#!/usr/bin/env python3
"""Read/search Reader research files, including compacted sources, without writes."""
from __future__ import annotations
import argparse
import json
import shutil
import sqlite3
import ssl
import subprocess
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


def read_github_code(url: str, start: int = 1, end: int | None = None) -> str:
    """Read a referenced immutable GitHub file as text, without downloading to disk."""
    parsed = urlsplit(url)
    parts = parsed.path.strip('/').split('/')
    if parsed.scheme != 'https' or parsed.hostname != 'github.com' or len(parts) < 5 or parts[2] != 'blob':
        raise ValueError('Expected an https://github.com/owner/repo/blob/COMMIT/file URL')
    commit = parts[3]
    if len(commit) != 40 or any(char not in '0123456789abcdefABCDEF' for char in commit):
        raise ValueError('Use the full fixed commit hash cited by the article')
    raw = 'https://raw.githubusercontent.com/' + '/'.join([*parts[:2], *parts[3:]])
    context = ssl.create_default_context()
    # python.org builds on macOS may not include the system CA bundle.
    if Path('/etc/ssl/cert.pem').is_file():
        context.load_verify_locations('/etc/ssl/cert.pem')
    with urlopen(Request(raw, headers={'User-Agent': 'PaperReader/1.0'}), timeout=60, context=context) as response:
        content = response.read().decode('utf-8')
    return f'Source: {url}\nFetched: {raw}\n\n' + '\n'.join(
        f'{i}: {line}' for i, line in enumerate(content.splitlines(), 1)
        if i >= start and (end is None or i <= end))


class ResearchMaterials:
    def __init__(self, task_dir: Path):
        self.root = task_dir.resolve()
        self.database = self.root / 'artifacts.sqlite3'

    def path(self, key: str) -> Path:
        relative = PurePosixPath(key)
        if relative.is_absolute() or '..' in relative.parts or not relative.parts:
            raise ValueError('Use a task-relative research file path')
        if relative.parts[0] not in {'papers', 'sources'} and key not in {'REPORT.md', 'SOURCES.md'}:
            raise ValueError('Only research documents and sources are supported')
        path = self.root.joinpath(*relative.parts).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError('Research file is outside the task directory')
        return path

    def inventory(self) -> list[str]:
        keys = set()
        for folder in ('papers', 'sources'):
            for path in (self.root / folder).rglob('*'):
                if path.is_file() and path.resolve().is_relative_to(self.root):
                    keys.add(path.relative_to(self.root).as_posix())
        for key in ('REPORT.md', 'SOURCES.md'):
            if (self.root / key).is_file():
                keys.add(key)
        if self.database.is_file():
            with sqlite3.connect(self.database.as_uri() + '?mode=ro', uri=True) as connection:
                for (key,) in connection.execute('SELECT path FROM files ORDER BY path'):
                    try:
                        self.path(key)
                    except ValueError:
                        continue
                    keys.add(key)
        return sorted(keys)

    def read(self, key: str, first_page: int | None = None, last_page: int | None = None) -> str:
        path = self.path(key)
        if path.suffix.lower() == '.pdf':
            command = [shutil.which('pdftotext') or 'pdftotext', '-layout']
            if first_page is not None:
                command += ['-f', str(first_page)]
            if last_page is not None:
                command += ['-l', str(last_page)]
            result = subprocess.run([*command, str(path), '-'], capture_output=True, text=True, timeout=120, check=True)
            return result.stdout
        if path.is_file():
            return path.read_text(encoding='utf-8')
        if self.database.is_file():
            with sqlite3.connect(self.database.as_uri() + '?mode=ro', uri=True) as connection:
                row = connection.execute('SELECT content FROM files WHERE path = ?', (key,)).fetchone()
            if row:
                return bytes(row[0]).decode('utf-8')
        raise FileNotFoundError(key)

    def search(self, query: str, prefix: str = '') -> list[dict]:
        matches = []
        for key in self.inventory():
            if not key.startswith(prefix):
                continue
            # PDF extraction is explicit via read; text artifacts are searchable.
            if Path(key).suffix.lower() not in {'.md', '.txt', '.py', '.json', '.yaml', '.yml', '.html', '.js', '.toml', '.csv', '.rst'}:
                continue
            try:
                lines = self.read(key).splitlines()
            except UnicodeDecodeError:
                continue
            for number, line in enumerate(lines, 1):
                if query.casefold() in line.casefold():
                    matches.append({'path': key, 'line': number, 'text': line})
        return matches


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--task-dir', type=Path, required=True)
    actions = parser.add_subparsers(dest='action', required=True)
    actions.add_parser('list')
    read = actions.add_parser('read')
    read.add_argument('path')
    read.add_argument('--start', type=int, help='Optional first line, inclusive, 1-based')
    read.add_argument('--end', type=int, help='Optional last line, inclusive')
    read.add_argument('--first-page', type=int)
    read.add_argument('--last-page', type=int)
    search = actions.add_parser('search')
    search.add_argument('query')
    search.add_argument('--prefix', default='')
    code = actions.add_parser('github-code', help='Read a fixed-commit GitHub file with line numbers')
    code.add_argument('url')
    code.add_argument('--start', type=int, default=1)
    code.add_argument('--end', type=int)
    args = parser.parse_args()
    materials = ResearchMaterials(args.task_dir)
    if args.action == 'github-code':
        if args.start < 1 or (args.end is not None and args.end < args.start):
            parser.error('Use a positive, ascending line range')
        print(read_github_code(args.url, args.start, args.end))
    elif args.action == 'list':
        print(json.dumps(materials.inventory(), ensure_ascii=False))
    elif args.action == 'search':
        print(json.dumps(materials.search(args.query, args.prefix), ensure_ascii=False))
    else:
        for name in ('start', 'end', 'first_page', 'last_page'):
            value = getattr(args, name)
            if value is not None and value < 1:
                parser.error('Line and page numbers must be positive')
        content = materials.read(args.path, args.first_page, args.last_page)
        if args.start is not None or args.end is not None:
            print('\n'.join(content.splitlines()[(args.start or 1)-1:args.end]))
        else:
            print(content, end='')


if __name__ == '__main__':
    main()
