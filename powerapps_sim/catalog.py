"""Portable authored list definitions, separate from the simulation database."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import os
import tempfile


def atomic_write(target, content):
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.write-', dir=target.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(content if isinstance(content, bytes) else content.encode('utf-8'))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def json_text(value):
    # JSON permits UTF-16 code units; UTF-8 files require isolated surrogates escaped.
    return (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + '\n').encode('utf-8', errors='backslashreplace').decode('utf-8')


def normalize_definition(definition):
    if not isinstance(definition, dict):
        raise ValueError('List definition must be an object')
    definition = deepcopy(definition)
    definition.setdefault('fields', {})
    fields = definition['fields']
    if not isinstance(fields, dict) or any(not isinstance(v, dict) for v in fields.values()):
        raise ValueError('List definition needs column objects in fields')
    definition.setdefault('mapping', {k: v.get('title', k) for k, v in fields.items()})
    definition.setdefault('required', [])
    definition.setdefault('choices', {})
    definition.setdefault('lookups', {})
    definition.setdefault('writable', True)
    return definition


class SchemaCatalog:
    def __init__(self, root):
        self.root = Path(root)
        if self.root.is_symlink():
            raise ValueError('The lists directory cannot be a symbolic link')

    def filename(self, name):
        label = re.sub(r'[^a-zA-Z0-9_-]+', '-', name).strip('-')[:60] or 'list'
        return f'{label}-{hashlib.sha256(name.encode()).hexdigest()[:12]}.json'

    def read(self):
        found = {}
        for target in sorted(self.root.glob('*.json')):
            if target.is_symlink():
                raise ValueError('List schema files cannot be symbolic links')
            value = json.loads(target.read_text(encoding='utf-8-sig'))
            if not isinstance(value, dict) or value.get('format_version') != 1:
                raise ValueError(f'{target.name}: expected schema format_version 1')
            name = value.get('name')
            if not isinstance(name, str) or not name.strip():
                raise ValueError(f'{target.name}: list name is required')
            if name in found:
                raise ValueError(f'Duplicate authored list {name}')
            found[name] = (target, normalize_definition(value.get('definition')))
        return found

    def path(self, name):
        existing = self.read().get(name)
        return existing[0] if existing else self.root / self.filename(name)

    def write(self, name, definition):
        target = self.path(name)
        atomic_write(target, json_text({'format_version': 1, 'name': name, 'definition': definition}))
        return target
