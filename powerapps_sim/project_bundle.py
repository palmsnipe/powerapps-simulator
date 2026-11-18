"""Portable simulator project archives. Native Power Apps exports stay separate."""
from contextlib import closing
from io import BytesIO
import json
from pathlib import Path, PurePosixPath
from stat import S_ISLNK
from tempfile import TemporaryDirectory
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile

from .catalog import json_text
from .source import Project, safe_path
from .store import ListStore

FORMAT = 'powerapps-simulator-project'
EXTENSION = '.pasim'
MAX_EXPANDED = 150_000_000
MAX_UPLOAD = 50_000_000
MAX_ENTRIES = 12_000
MANIFEST = 'manifest.json'
CONFIG = 'emulator.json'
RECORDS = 'records.json'
METADATA = ('metadata/datasources.json', 'metadata/checker.json', 'metadata/schema-catalog.json')


def allowed(name):
    parts = PurePosixPath(name).parts
    if name in (MANIFEST, CONFIG, RECORDS, *METADATA):
        return True
    if len(parts) < 2:
        return False
    if parts[0] == 'Src':
        return name.endswith(('.yaml', '.yml'))
    if parts[0] == 'Assets':
        return True
    if len(parts) == 2 and parts[0] == 'lists':
        return name.endswith('.json')
    return len(parts) == 2 and parts[0] == 'tests' and name.endswith('.workflow.json')


def export_bundle(workspace, *, include_records=False):
    if type(include_records) is not bool:
        raise ValueError('include_records must be Boolean')
    with workspace.lock:
        root = workspace.project.root
        if (root / 'metadata').is_symlink():
            raise ValueError('Project bundles do not follow symlinks')
        paths = [root / CONFIG, *(root / name for name in METADATA if (root / name).exists())]
        for folder in ('Src', 'Assets', 'lists', 'tests'):
            directory = root / folder
            if directory.is_symlink():
                raise ValueError('Project bundles do not follow symlinks')
            paths.extend(sorted(path for path in directory.rglob('*')
                                if allowed(path.relative_to(root).as_posix()) and (path.is_file() or path.is_symlink())))
        if any(path.is_symlink() for path in paths):
            raise ValueError('Project bundles do not follow symlinks')
        for path in paths:
            safe_path(root, path.relative_to(root).as_posix())
        if len(paths) + 2 > MAX_ENTRIES:
            raise ValueError('Project bundle has too many files')
        entries = {MANIFEST: json_text({'format': FORMAT, 'version': 1, 'includes_records': include_records})}
        if include_records:
            db = workspace.runtime.store.db
            entries[RECORDS] = json_text({
                'items': [[name, item_id, json.loads(record)] for name, item_id, record in
                          db.execute('SELECT list_name,id,record FROM items ORDER BY list_name,id')],
                'sequences': dict(db.execute('SELECT name,high_water FROM list_sequences ORDER BY name')),
            })
        if sum(path.stat().st_size for path in paths) + sum(len(text.encode()) for text in entries.values()) > MAX_EXPANDED:
            raise ValueError('Project bundle exceeds the uncompressed size limit')
        result = BytesIO()
        with ZipFile(result, 'w', compression=ZIP_DEFLATED) as archive:
            for name, text in entries.items():
                archive.writestr(name, text)
            for path in paths:
                archive.write(path, path.relative_to(root).as_posix())
        if result.tell() > MAX_UPLOAD:
            raise ValueError('Project bundle exceeds the 50 MB import limit')
        return result.getvalue()


def restore_records(store, payload):
    if not isinstance(payload, dict) or set(payload) != {'items', 'sequences'} or not isinstance(
        payload['items'], list
    ) or not isinstance(payload['sequences'], dict):
        raise ValueError('Invalid project bundle records')
    sequences = payload['sequences']
    if any(name not in store.definitions or type(high) is not int or not 1 <= high < 2**63
           for name, high in sequences.items()):
        raise ValueError('Invalid project bundle record sequence')
    rows, seen = [], set()
    for row in payload['items']:
        if not isinstance(row, list) or len(row) != 3:
            raise ValueError('Invalid project bundle record')
        name, item_id, record = row
        if not isinstance(name, str) or name not in store.definitions or type(item_id) is not int or not (
            1 <= item_id <= sequences.get(name, 0)
        ) or not isinstance(record, dict) or ('ID' in record and record['ID'] != item_id):
            raise ValueError('Invalid project bundle record identity')
        if (name, item_id) in seen:
            raise ValueError('Duplicate project bundle record ID')
        seen.add((name, item_id))
        # Restore stored values verbatim, including legacy nullable and unknown fields.
        # SQLite is freshly created from the local schema catalog.
        rows.append((name, item_id, json.dumps(record, allow_nan=False)))
    with store.db:
        store.db.executemany('INSERT INTO items(list_name,id,record) VALUES (?,?,?)', rows)
        store.db.executemany('INSERT INTO list_sequences(name,high_water) VALUES (?,?)', sequences.items())


def import_bundle(payload, destination):
    if destination.exists() or destination.is_symlink():
        raise ValueError('Choose a new project directory')
    if len(payload) > MAX_UPLOAD:
        raise ValueError('Project bundle exceeds the 50 MB import limit')
    with ZipFile(BytesIO(payload)) as archive, TemporaryDirectory(prefix='.bundle-', dir=destination.parent) as tmp:
        root = Path(tmp) / 'project'
        root.mkdir()
        infos = archive.infolist()
        if len(infos) > MAX_ENTRIES or sum(info.file_size for info in infos) > MAX_EXPANDED:
            raise ValueError('Project bundle exceeds the expanded size or file count limit')
        names = set()
        spellings = set()
        for info in infos:
            name = info.filename
            if (not allowed(name) or info.is_dir() or info.flag_bits & 1
                or info.compress_type not in (ZIP_STORED, ZIP_DEFLATED)
                or PurePosixPath(name).as_posix() != name or '\\' in name
                or S_ISLNK(info.external_attr >> 16) or name.casefold() in spellings):
                raise ValueError('Unsupported, duplicate or unsafe project bundle entry')
            safe_path(root, name)
            names.add(name)
            spellings.add(name.casefold())
        if not {MANIFEST, CONFIG} <= names:
            raise ValueError('Project bundle needs a manifest and settings')
        manifest = json.loads(archive.read(MANIFEST))
        if (not isinstance(manifest, dict) or manifest.get('format') != FORMAT or
            type(manifest.get('version')) is not int or manifest['version'] != 1 or
            type(manifest.get('includes_records')) is not bool or manifest['includes_records'] != (RECORDS in names)):
            raise ValueError('Unsupported simulator project bundle manifest')
        # Reject file/parent collisions before writing anything to the staging directory.
        for name in names:
            if any(parent.as_posix().casefold() in spellings for parent in PurePosixPath(name).parents):
                raise ValueError('Project bundle entry conflicts with a directory')
        for info in infos:
            if info.filename not in (MANIFEST, RECORDS):
                target = safe_path(root, info.filename)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.read(info))
        config = json.loads((root / CONFIG).read_text(encoding='utf-8'))
        if not isinstance(config, dict) or not isinstance(config.get('title'), str) or (
            'environment' in config and not isinstance(config['environment'], dict)
        ) or ('viewport' in config and not isinstance(config['viewport'], dict)):
            raise ValueError('Invalid project bundle settings')
        project = Project(root)
        if not project.documents or project.source_errors or not project.screens:
            raise ValueError('Project bundle needs valid source with at least one screen')
        with closing(ListStore(root / 'data.sqlite', project.read_json('metadata/datasources.json', {}),
                               schema_root=root / 'lists')) as store:
            if RECORDS in names:
                restore_records(store, json.loads(archive.read(RECORDS)))
        # Check that the runtime can load the published files without executing startup.
        from .runtime import Runtime
        with closing(Runtime(project)):
            pass
        root.rename(destination)
    return Project(destination)
