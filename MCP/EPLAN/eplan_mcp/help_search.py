"""Local FTS5 search over user-owned SDK XML, HTML and notes; no uploads."""
from __future__ import annotations

import hashlib
from contextlib import closing
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
import xml.etree.ElementTree as ET

VERSION = '2.9'
MAX_FILE = 32 * 1024 * 1024  # Installed 2.9 DataModel SDK XML exceeds 12 MiB.
MAX_FILES = 12000


class PlainHTML(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {'script', 'style'}:
            self.hidden += 1

    def handle_endtag(self, tag):
        if tag in {'script', 'style'} and self.hidden:
            self.hidden -= 1

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def documents(path):
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if path.suffix.lower() == '.xml':
        # .NET SDK XML has one independently searchable record per API member.
        root = ET.fromstring(raw)
        members = root.findall('./members/member')
        for member in members:
            name = member.get('name', '')
            body = ' '.join(' '.join(member.itertext()).split())
            yield name, name + ' ' + body, digest
        return
    text = raw.decode('utf-8-sig', errors='replace')
    if path.suffix.lower() in {'.html', '.htm'}:
        parser = PlainHTML()
        parser.feed(text)
        text = ' '.join(parser.parts)
    yield path.stem, ' '.join(text.split())[:160000], digest


def index(settings):
    if not settings.help_roots:
        return {'ok': False, 'error': 'HELP_ROOTS_NOT_CONFIGURED', 'uploaded': False}
    target = settings.workspace / 'artifacts' / 'help-search.sqlite3'
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='help-index-', suffix='.sqlite3', dir=target.parent)
    os.close(fd)
    files, records, skipped, errors = 0, 0, 0, []
    try:
        with closing(sqlite3.connect(temporary)) as db, db:
            db.execute('CREATE VIRTUAL TABLE docs USING fts5(title, body, path UNINDEXED, sha256 UNINDEXED)')
            db.execute('CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT)')
            seen = set()
            for root in settings.help_roots:
                if not root.is_dir():
                    raise ValueError('Configured help directory is unavailable: ' + str(root))
                for folder, dirs, names in os.walk(root, followlinks=False):
                    dirs[:] = [n for n in sorted(dirs) if not (Path(folder) / n).is_symlink()]
                    for name in sorted(names):
                        path = Path(folder) / name
                        if path.suffix.lower() not in {'.xml', '.html', '.htm', '.md', '.txt'}:
                            continue
                        if path.is_symlink() or path.resolve() in seen:
                            continue
                        if not path.resolve().is_relative_to(root.resolve()):
                            continue
                        seen.add(path.resolve())
                        if path.stat().st_size > MAX_FILE:
                            skipped += 1
                            continue
                        files += 1
                        if files > MAX_FILES:
                            raise ValueError('Help file limit exceeded; configure narrower help_roots')
                        try:
                            for title, body, digest in documents(path):
                                if body:
                                    db.execute('INSERT INTO docs VALUES(?,?,?,?)', (title, body, str(path), digest))
                                    records += 1
                        except (ValueError, ET.ParseError) as exc:
                            errors.append({'file': str(path), 'error': str(exc)})
            db.executemany('INSERT INTO metadata VALUES(?,?)', [
                ('version', VERSION), ('roots', json.dumps([str(p) for p in settings.help_roots])),
            ])
            if records == 0:
                raise ValueError('No readable documentation records; previous index preserved')
        os.replace(temporary, target)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return {'ok': True, 'files': files, 'records': records, 'skipped_oversize': skipped,
            'parse_errors': errors[:20], 'path': str(target), 'version': VERSION,
            'version_basis': 'configured_target_not_source_autodetection', 'uploaded': False}


def search(settings, query, limit=5):
    if type(limit) is not int or not 1 <= limit <= 20:
        raise ValueError('limit must be between 1 and 20')
    tokens = re.findall(r'[\w.]+', query, flags=re.UNICODE)
    if not tokens or len(query) > 500:
        raise ValueError('Provide a short API name or documentation query')
    target = settings.workspace / 'artifacts' / 'help-search.sqlite3'
    if not target.is_file():
        return {'ok': False, 'error': 'HELP_INDEX_NOT_BUILT', 'results': []}
    expression = ' AND '.join('"' + token.replace('"', '""') + '"' for token in tokens)
    with closing(sqlite3.connect(target.as_uri() + '?mode=ro', uri=True)) as db:
        metadata = dict(db.execute('SELECT key,value FROM metadata'))
        if metadata.get('version') != VERSION or json.loads(metadata['roots']) != [str(p) for p in settings.help_roots]:
            return {'ok': False, 'error': 'HELP_INDEX_CONFIGURATION_CHANGED', 'results': []}
        rows = db.execute("SELECT title,snippet(docs,1,'[',']',' … ',40),path,sha256 FROM docs WHERE docs MATCH ? ORDER BY bm25(docs) LIMIT ?", (expression, limit)).fetchall()
    results = []
    for title, snippet, path, digest in rows:
        p = Path(path)
        valid_path = any(p.resolve().is_relative_to(root.resolve()) for root in settings.help_roots)
        fresh = valid_path and p.is_file() and p.stat().st_size <= MAX_FILE and hashlib.sha256(p.read_bytes()).hexdigest() == digest
        results.append({'title': title, 'snippet': snippet, 'path': path, 'sha256': digest, 'source_unchanged': fresh})
    return {'ok': True, 'version': VERSION, 'source': 'local_documentation_not_live_API',
            'version_basis': 'configured_target_not_source_autodetection',
            'query': query, 'results': results, 'uploaded': False}
