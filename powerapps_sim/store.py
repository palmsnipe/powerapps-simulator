"""SQLite list adapter retaining SharePoint-shaped records and schema metadata."""
from __future__ import annotations

import csv
from datetime import date, datetime, timezone
from io import StringIO
import json
import sqlite3
from copy import deepcopy
from pathlib import Path
import uuid

from .catalog import SchemaCatalog, normalize_definition, atomic_write, json_text

from .numeric import NUMBERS, decimal_value
from .syntax import FxError
from .temporal import schema_value, storage_value
from .sharepoint import complex_kind
from .data_errors import tracked_write


def reject_errors(value):
    """SQLite stores list values, never unresolved language errors."""
    if isinstance(value, FxError):
        raise value
    if isinstance(value, dict):
        for cell in value.values():
            reject_errors(cell)
    elif isinstance(value, list):
        for cell in value:
            reject_errors(cell)


class DataSource:
    def __init__(self, store, name):
        self.store, self.name = store, name

    def rows(self):
        return [self.record(row) for row in self.store.rows(self.name)]

    def record(self, row):
        definition = self.store.definitions[self.name]
        from .tables import derived_record
        return derived_record(row, {key: schema_value(value, definition['fields'].get(self.store.internal_name(self.name, key), {})) for key, value in row.items()})


class ListStore:
    def __init__(self, path, metadata=None, schema_root=None):
        self.catalog = None
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS lists(name TEXT PRIMARY KEY, definition TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS items(list_name TEXT NOT NULL, id INTEGER NOT NULL, record TEXT NOT NULL,
                PRIMARY KEY(list_name,id), FOREIGN KEY(list_name) REFERENCES lists(name));
            CREATE TABLE IF NOT EXISTS list_sequences(name TEXT PRIMARY KEY, high_water INTEGER NOT NULL);
        """)
        with self.db:
            for name,high_water in self.db.execute('SELECT list_name,MAX(id) FROM items GROUP BY list_name').fetchall():
                self._remember_id(name,high_water)
        self.definitions, self.failures = {}, {}
        self.operation_errors, self.error_seen, self.operation_depth = {}, {}, {}
        self.clock = None
        self.actor = None  # Runtime supplies the currently simulated user, lazily.
        for row in self.db.execute("SELECT * FROM lists"):
            self.definitions[row["name"]] = json.loads(row["definition"])
        for d in (metadata or {}).get("DataSources", []):
            if d.get("Type") == "ConnectedDataSourceInfo":
                raw = d.get("DataEntityMetadataJson", {})
                md = raw.get(d.get("TableName"), next(iter(raw.values()), {})) if isinstance(raw, dict) else json.loads(raw)
                if isinstance(md, str):
                    md = json.loads(md)
                schema = md.get("schema", {}).get("items", {})
                self.add_list(d["Name"], {"fields": schema.get("properties", {}),
                    "required": schema.get("required", []), "mapping": d.get("ConnectedDataSourceInfoNameMapping", {}),
                    "choices": {}, "lookups": {}, "metadata_gaps": [], "writable": d.get("IsWritable", True)})
            elif d.get("Type") == "StaticDataSourceInfo":
                # These are authoring placeholders, not SharePoint lists.
                pass
        if schema_root is not None:
            self.catalog = SchemaCatalog(schema_root)
            try:
                self.sync_catalog()
            except Exception:
                self.close()
                raise

    def close(self):
        self.db.close()

    def add_list(self, name, definition):
        if name in self.definitions:
            return
        definition = normalize_definition(definition)
        definition.setdefault("fields", {})
        definition.setdefault("mapping", {k: v.get("title", k) for k, v in definition["fields"].items()})
        definition.setdefault("required", [])
        definition.setdefault("choices", {})
        definition.setdefault("lookups", {})
        definition.setdefault("writable", True)
        self.validate_definition(definition)
        for key, field in definition["fields"].items():
            kind = complex_kind(field, definition, key)
            if kind == 'choice' and key not in definition['choices']:
                definition.setdefault("metadata_gaps", []).append(f"{key}: choice options need local configuration")
            elif kind == 'lookup' and key not in definition['lookups']:
                definition.setdefault("metadata_gaps", []).append(f"{key}: lookup target needs local configuration")
        self.definitions[name] = definition
        self.save_definition(name)

    def save_definition(self, name):
        self.validate_definition(self.definitions[name])
        self.db.execute("INSERT OR REPLACE INTO lists VALUES(?,?)", (name, json.dumps(self.definitions[name])))
        self.db.commit()
        if self.catalog:
            self.catalog.write(name, self.definitions[name])
            self.catalog_marker()

    def catalog_marker(self):
        atomic_write(self.catalog.root.parent / 'metadata/schema-catalog.json', json_text({
            'format_version': 1, 'lists': sorted(self.definitions),
            'note': 'Existing SQLite schemas were copied without replacing item records.'}))

    def plan_schemas(self, changes, migrations=None):
        """Validate schema/data changes without committing or editing authored files."""
        migrations = migrations or {}
        if not isinstance(changes, dict) or not isinstance(migrations, dict):
            raise ValueError('List changes and migrations must be objects')
        if set(migrations) - set(changes):
            raise ValueError('A migration must accompany a changed list')
        definitions = {**deepcopy(self.definitions), **{n: normalize_definition(d) for n, d in changes.items()}}
        rows, reports = {}, []
        for name, definition in definitions.items():
            if not isinstance(name, str) or not name.strip():
                raise ValueError('List name is required')
            self.validate_definition(definition)
            if name in changes and any(target not in definitions for target in definition['lookups'].values()):
                raise ValueError(f'{name}: a lookup target is not a configured list')
        for name in changes:
            old = self.definitions.get(name, {'fields': {}})
            new = definitions[name]
            migration = migrations.get(name, {})
            if not isinstance(migration, dict) or set(migration) - {'rename_columns', 'drop_columns'}:
                raise ValueError('Migration supports rename_columns and drop_columns')
            renames, drops = migration.get('rename_columns', {}), migration.get('drop_columns', [])
            if not isinstance(renames, dict) or any(not isinstance(v, str) for v in renames.values()) or not isinstance(drops, list) or any(not isinstance(v, str) for v in drops):
                raise ValueError('Migration needs column-name objects/lists')
            if len(set(renames.values())) != len(renames):
                raise ValueError('Column rename destinations must be unique')
            removed = set(old['fields']) - set(new['fields'])
            if set(renames) | set(drops) != removed or set(renames) & set(drops):
                raise ValueError(f'{name}: removed columns require explicit rename_columns or drop_columns: {sorted(removed)}')
            if any(target not in new['fields'] or target in old['fields'] for target in renames.values()):
                raise ValueError('Rename targets must be newly declared columns')
            if 'ID' in old['fields'] and old['fields']['ID'] != new['fields'].get('ID'):
                raise ValueError('The ID column contract cannot be changed')
            stored = [(row['id'], json.loads(row['record'])) for row in self.db.execute('SELECT id,record FROM items WHERE list_name=? ORDER BY id', (name,))]
            prepared, changed = [], 0
            for item_id, record in stored:
                candidate = deepcopy(record)
                for column in removed:
                    value = candidate.pop(column, None)
                    if column in renames:
                        candidate[renames[column]] = value
                for column, field in new['fields'].items():
                    if column not in candidate and field.get('x-ms-permission') != 'read-only':
                        candidate[column] = deepcopy(field.get('default'))
                changed += candidate != record
                prepared.append((item_id, candidate))
            rows[name] = prepared
            reports.append({'list': name, 'created': name not in self.definitions,
                'added_columns': sorted(set(new['fields']) - set(old['fields'])),
                'removed_columns': sorted(removed), 'rename_columns': renames, 'drop_columns': drops,
                'records_checked': len(stored), 'records_changed': changed})
        previous = self.definitions
        previous_failures = self.failures
        self.definitions = definitions
        self.failures = {}
        try:
            for name in changes:
                for column, field in definitions[name]['fields'].items():
                    if field.get('default') is not None:
                        self.validate(name, {column: field['default']}, fields={column})
            for name, prepared in rows.items():
                for item_id, record in prepared:
                    try:
                        self.validate(name, record)
                    except FxError as error:
                        raise FxError(f'{name} item {item_id}: {error.message}', error.kind) from None
        finally:
            self.definitions = previous
            self.failures = previous_failures
        return definitions, rows, reports

    def sync_catalog(self):
        """Load authored files; bootstrap legacy schemas without touching records."""
        entries = self.catalog.read()
        marker = self.catalog.root.parent / 'metadata/schema-catalog.json'
        if marker.exists():
            missing = (set(json.loads(marker.read_text(encoding='utf-8'))['lists']) | set(self.definitions)) - set(entries)
            if missing:
                raise ValueError(f'Missing authored schemas: {sorted(missing)}; restore the files before restarting')
        else:
            for name, definition in self.definitions.items():
                if name not in entries:
                    self.catalog.write(name, definition)
            entries = self.catalog.read()
        changes = {n: d for n, (_, d) in entries.items() if self.definitions.get(n) != d}
        definitions, rows, _ = self.plan_schemas(changes)
        if changes:
            # Keep a database snapshot when a file edit materializes into records.
            backup = self.catalog.root.parent / 'metadata/catalog-sync' / (uuid.uuid4().hex + '.sqlite')
            backup.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(backup) as destination:
                self.db.backup(destination)
            with self.db:
                for name in changes:
                    self.db.execute('INSERT OR REPLACE INTO lists VALUES(?,?)', (name, json.dumps(definitions[name])))
                    for item_id, record in rows[name]:
                        self.db.execute('UPDATE items SET record=? WHERE list_name=? AND id=?', (json.dumps(record), name, item_id))
            self.definitions = definitions
        self.catalog_marker()

    def validate_definition(self, definition):
        fields = definition.get("fields")
        if not isinstance(fields, dict) or any(not isinstance(k, str) or not k.strip() or not isinstance(v, dict) for k, v in fields.items()):
            raise FxError("Schema fields must map column names to objects")
        if any(v.get("type") not in (None, "string", "number", "integer", "boolean", "object", "array") for v in fields.values()):
            raise FxError("Unsupported schema field type", "Unsupported")
        required = definition.get("required", [])
        if not isinstance(required, list) or any(not isinstance(k, str) or k not in fields for k in required):
            raise FxError("Required columns must exist in fields")
        for column, field in fields.items():
            self.validate_field_schema(column, field)
        if not isinstance(definition.get('writable', True), bool):
            raise FxError('writable must be Boolean', 'Validation')
        mapping = definition.get("mapping", {})
        if not isinstance(mapping, dict) or any(not isinstance(v, str) for v in mapping.values()):
            raise FxError("Column mapping values must be display names")
        if set(mapping) - set(fields) or len(set(mapping.get(k, k) for k in fields)) != len(fields):
            raise FxError('Column mappings must refer to fields and have unique display names', 'Validation')
        choices = definition.get("choices", {})
        if not isinstance(choices, dict) or any(not isinstance(v, list) or any(not isinstance(s, str) for s in v) for v in choices.values()):
            raise FxError("Choices must map column names to lists of text values")
        if set(choices) - set(fields):
            raise FxError('Choice columns must exist in fields', 'Validation')
        lookups = definition.get("lookups", {})
        if not isinstance(lookups, dict) or any(not isinstance(v, str) for v in lookups.values()):
            raise FxError("Lookup targets must be local list names")
        if set(lookups) - set(fields):
            raise FxError('Lookup columns must exist in fields', 'Validation')

    def validate_field_schema(self, label, schema):
        if not isinstance(schema, dict):
            raise FxError(f'{label}: field shape must be an object', 'Validation')
        if schema.get('type') not in (None, 'string', 'number', 'integer', 'boolean', 'object', 'array'):
            raise FxError(f'{label}: unsupported schema field type', 'Unsupported')
        props = schema.get('properties', {})
        if not isinstance(props, dict):
            raise FxError(f'{label}: properties must be an object', 'Validation')
        length = schema.get('maxLength')
        if length is not None and (type(length) is not int or length < 0):
            raise FxError(f'{label}: maxLength must be a nonnegative integer', 'Validation')
        from .validation import validate_bounds
        validate_bounds(label, schema)
        for key, child in props.items():
            self.validate_field_schema(f'{label}.{key}', child)
        if 'items' in schema:
            self.validate_field_schema(label + '[]', schema['items'])

    def source(self, name):
        if name not in self.definitions:
            raise FxError(f"Unknown list {name}")
        return DataSource(self, name)

    def check_failure(self, name, operation):
        if self.failures.get(name) in (operation, "all"):
            raise FxError(f"Simulated {operation} failure for {name}", "Network")

    def internal_name(self, name, field):
        d = self.definitions[name]
        if field in d["fields"]:
            return field
        return next((k for k, v in d.get("mapping", {}).items() if v == field), field)

    def display(self, name, row):
        d = self.definitions[name]
        # SharePoint exposes known nullable fields even when a record omits them.
        complete = {k: None for k in d["fields"]}
        complete.update(row)
        from .tables import SourceRecord
        mapping = d.get('mapping', {})
        return SourceRecord({mapping.get(k, k): v for k, v in complete.items()}, {display:internal for internal,display in mapping.items()}, source_name=name)

    def internal(self, name, row):
        return {self.internal_name(name, k): v for k, v in row.items()}

    def rows(self, name):
        reactive=getattr(self,'reactive',None)
        return reactive.leaf(('list',name),lambda:self._rows(name)) if reactive else self._rows(name)

    def _rows(self, name):
        self.check_failure(name, "read")
        return [self.display(name, json.loads(r[0])) for r in self.db.execute(
            "SELECT record FROM items WHERE list_name=? ORDER BY id", (name,))]

    def defaults(self, name):
        d = self.definitions[name]
        return self.display(name, {k: v.get("default") for k, v in d["fields"].items() if v.get("x-ms-permission") != "read-only"})

    def validate(self, name, record, *, fields=None):
        reject_errors(record)
        d = self.definitions[name]
        record = storage_value(record, {"properties": d["fields"]})
        required = set(d['required']) | {k for k, field in d['fields'].items() if field.get('required') is True}
        for k in sorted(required):
            if fields is not None and k not in fields:
                continue
            if record.get(k) is None or record.get(k) == "" or record.get(k) == []:
                raise FxError(f"{d['mapping'].get(k, k)} is required", "MissingRequired", column=k)
        for k, value in record.items():
            field = d["fields"].get(k)
            if field is None:
                raise FxError(f"Unknown column {k} in {name}", "Validation", column=k)
            try:
                self.validate_value(name, k, value, field, d['mapping'].get(k, k), complex_kind(field, d, k))
            except FxError as error:
                if error.column is None:
                    error.column = k
                raise

    def validate_value(self, name, key, value, field, label, complex_type=None):
        """Validate nested cells before any item write is committed."""
        d = self.definitions[name]
        if value is None:
            return
        kind = field.get("type")
        if kind == 'number' and field.get('format') == 'decimal' and isinstance(value, dict) and set(value) == {'$decimal'}:
            value = decimal_value(value['$decimal'])
        valid = {"string": isinstance(value, str), "boolean": isinstance(value, bool),
            "number": isinstance(value, NUMBERS) and not isinstance(value, bool),
            "integer": isinstance(value, int) and not isinstance(value, bool),
            "object": isinstance(value, dict), "array": isinstance(value, list)}.get(kind, True)
        if not valid:
            raise FxError(f"{label} expects {kind}", "Validation")
        if isinstance(value, str) and field.get('maxLength') is not None and len(value) > field['maxLength']:
            raise FxError(f"{label} exceeds maximum length", "Validation")
        from .validation import check_bounds
        check_bounds(label, value, field)
        if isinstance(value, list):
            for i, cell in enumerate(value):
                path = f'{label}[{i + 1}]'
                if complex_type and not isinstance(cell, dict):
                    raise FxError(f'{path} requires a {complex_type.title()} record', 'Validation')
                self.validate_value(name, key, cell, field.get('items', {}), path, complex_type)
        if isinstance(value, dict):
            p = field.get("properties", {})
            if complex_type == 'person':
                if not all(isinstance(value.get(k), str) and value[k].strip() for k in ('Claims', 'Email')):
                    raise FxError(f"{label} requires a Person record with Claims and Email", "Validation")
            elif complex_type == 'choice':
                options = d.get("choices", {}).get(key, [])
                if not isinstance(value.get("Value"), str) or options and value["Value"] not in options:
                    raise FxError(f"Invalid choice for {label}", "Validation")
            elif complex_type == 'lookup':
                if type(value.get('Id')) is not int or value['Id'] <= 0 or 'Value' not in value or value['Value'] is not None and not isinstance(value['Value'], str):
                    raise FxError(f"{label} requires a Lookup record with Id and Value", "Validation")
                target = d.get("lookups", {}).get(key)
                if target and not self.db.execute("SELECT 1 FROM items WHERE list_name=? AND id=?", (target, value["Id"])).fetchone():
                    raise FxError(f"Missing lookup target for {label}", "Validation")
            required = field.get('required', [])
            required = set(required) if isinstance(required, list) else set()
            required.update(k for k, v in p.items() if v.get('required') is True)
            if required:
                for child in sorted(required):
                    if value.get(child) is None or value.get(child) == '' or value.get(child) == []:
                        raise FxError(f'{label}.{child} is required', 'MissingRequired')
            for child, cell in value.items():
                if child in p:
                    self.validate_value(name, key, cell, p[child], f'{label}.{child}')
        if kind == "string" and field.get("format") in ("date", "date-time"):
            try:
                if field["format"] == "date":
                    date.fromisoformat(value[:10])
                else:
                    datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                raise FxError(f"Invalid date for {label}", "Validation") from None

    @tracked_write
    def patch(self, name, base, updates, *, system=False):
        self.check_failure(name, "write")
        d = self.definitions[name]
        if not d.get("writable", True) and not system:
            raise FxError(f"{name} is read-only", "ReadOnlyValue")
        base, updates = self.internal(name, base or {}), self.internal(name, updates)
        item_id = base.get("ID")
        old = self.db.execute("SELECT record FROM items WHERE list_name=? AND id=?", (name, item_id)).fetchone() if item_id else None
        if item_id and not old and not system:
            raise FxError(f"Item {item_id} no longer exists", "NotFound")
        for k in updates:
            if d["fields"].get(k, {}).get("x-ms-permission") == "read-only" and not system:
                raise FxError(f"{k} is read-only", "ReadOnlyValue", column=k)
        row = json.loads(old[0]) if old else self.internal(name, self.defaults(name))
        row.update(updates)
        if item_id is None:
            item_id = self.next_id(name)
        if "ID" in d["fields"]:
            row["ID"] = item_id
        stamp = self.clock or datetime.now(timezone.utc).isoformat()
        for key in ("Created", "Modified"):
            if key in d["fields"]:
                row[key] = row.get(key) or stamp if key == "Created" else stamp
        actor = self.actor() if callable(self.actor) else self.actor
        if actor:
            for key, display in (("Author", "Created By"), ("Editor", "Modified By")):
                field = next((k for k, s in d["fields"].items() if
                    (k == key or d.get("mapping", {}).get(k) == display) and
                    s.get("x-ms-permission") == "read-only" and "Claims" in s.get("properties", {})), None)
                if field is None:
                    continue
                if (key == "Author" and old) or (system and field in updates):
                    continue  # Preserve creator and explicitly restored fixture metadata.
                row[field] = deepcopy(actor)
                claims_field = field + "#Claims"
                if claims_field in d["fields"]:
                    row[claims_field] = actor["Claims"]
        row = storage_value(row, {"properties": d["fields"]})
        self.validate(name, row)
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO items VALUES(?,?,?)", (name, item_id, json.dumps(row)))
            self._remember_id(name,item_id)
        return self.display(name, row)

    def _remember_id(self, name, item_id):
        self.db.execute('INSERT INTO list_sequences VALUES(?,?) ON CONFLICT(name) DO UPDATE SET high_water=MAX(high_water,excluded.high_water)',(name,int(item_id)))

    def next_id(self, name):
        saved = self.db.execute('SELECT high_water FROM list_sequences WHERE name=?',(name,)).fetchone()
        current = self.db.execute('SELECT COALESCE(MAX(id),0) FROM items WHERE list_name=?',(name,)).fetchone()[0]
        item_id = max(saved[0] if saved else 0,current)+1
        if item_id>2**63-1:
            raise FxError('List item ID range is exhausted','ConstraintViolated')
        return item_id

    def remove_identity(self, name, record):
        from .fx import observe
        item_id = observe(self.internal(name,record).get('ID'))
        if item_id is None:
            raise FxError('Remove requires an existing item ID','NotFound')
        try:
            if isinstance(item_id,bool) or not isinstance(item_id,NUMBERS) or int(item_id)!=item_id:
                raise ValueError()
            item_id = int(item_id)
        except (ValueError,OverflowError):
            raise FxError('Remove identity requires an integer ID','Type') from None
        if not 0<item_id<=2**63-1:
            raise FxError('Remove identity requires a positive ID','Type')
        return item_id

    @tracked_write
    def remove(self, name, record):
        """Delete one local item without changing the list's ID high-water mark."""
        self.check_failure(name,'write')
        if not self.definitions[name].get('writable',True):
            raise FxError(name+' is read-only','ReadOnlyValue')
        item_id = self.remove_identity(name,record)
        with self.db:
            deleted = self.db.execute('DELETE FROM items WHERE list_name=? AND id=?',(name,item_id))
            if deleted.rowcount!=1:
                raise FxError('Remove record was not found','NotFound')

    @tracked_write
    def replace(self, name, base, replacement):
        """Replace editable fields, retaining connector-managed identity/audit data."""
        reject_errors(replacement)
        definition = self.definitions[name]
        base, replacement = self.internal(name, base), self.internal(name, replacement)
        item_id = base.get('ID')
        old = self.db.execute('SELECT record FROM items WHERE list_name=? AND id=?', (name, item_id)).fetchone()
        if not old:
            raise FxError('Update record was not found', 'NotFound')
        old = json.loads(old[0])
        if 'ID' in definition['fields'] and replacement.get('ID') != item_id:
            raise FxError('Update must reaffirm the existing ID', 'ReadOnlyValue')
        normalized = storage_value(replacement, {'properties':definition['fields']})
        for key, value in normalized.items():
            if key not in definition['fields']:
                raise FxError(f'Unknown column {key} in {name}', 'Name', column=key)
            if key == 'ID' or definition['fields'][key].get('x-ms-permission') == 'read-only' or key in ('Created', 'Modified'):
                previous = storage_value(schema_value(old.get(key), definition['fields'][key]), definition['fields'][key])
                if value != previous:
                    raise FxError(f'{key} is read-only', 'ReadOnlyValue', column=key)
        updates = {key:replacement.get(key) for key, schema in definition['fields'].items()
                   if key not in ('ID','Created','Modified') and schema.get('x-ms-permission') != 'read-only'}
        return self.patch(name, base, updates)

    def choices(self, name, field, people):
        key = self.internal_name(name, field)
        d = self.definitions[name]
        if key not in d['fields']:
            raise FxError(f'Unknown column {field} in {name}', 'Name')
        schema = d["fields"].get(key, {})
        if complex_kind(schema, d, key) == 'person':
            return people
        if key in d.get("lookups", {}):
            if d['lookups'][key] not in self.definitions:
                raise FxError(f'Configure a local lookup target for {name}.{field}', 'Configuration')
            return [{"Id": r["ID"], "Value": r.get("Title", str(r["ID"]))} for r in self.rows(d["lookups"][key])]
        if key in d.get("choices", {}):
            return [{"Value": v} for v in d["choices"][key]]
        raise FxError(f"Configure local choice options or lookup target for {name}.{field}", "Configuration")

    def export_csv(self, name):
        rows = self.rows(name)
        fields = list(dict.fromkeys(k for row in rows for k in row)) or list(self.definitions[name]["mapping"].values())
        out = StringIO()
        writer = csv.DictWriter(out, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list, bool)) else v for k, v in row.items()})
        return out.getvalue()

    def import_rows(self, name, rows, replace=False):
        """Validate an entire import before persisting any row; imports can restore IDs."""
        prepared = []
        seen = set()
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise FxError("Records must be a JSON array of objects")
        for row in rows:
            internal = self.internal(name, row)
            for k, v in list(internal.items()):
                schema = self.definitions[name]["fields"].get(k, {})
                if v == "":
                    internal[k] = None
                elif isinstance(v, str) and schema.get("type") in ("object", "array", "number", "integer", "boolean"):
                    try:
                        internal[k] = json.loads(v)
                    except ValueError:
                        raise FxError(f"Invalid JSON value for {k}") from None
            self.validate(name, internal)
            if internal.get("ID") is not None:
                if internal["ID"] in seen:
                    raise FxError("Duplicate item ID in import")
                seen.add(internal["ID"])
            prepared.append(internal)
        with self.db:
            if replace:
                self.db.execute("DELETE FROM items WHERE list_name=?", (name,))
                self.db.execute('DELETE FROM list_sequences WHERE name=?',(name,))
            for row in prepared:
                item_id = row.get("ID") or self.next_id(name)
                if "ID" in self.definitions[name]["fields"]:
                    row["ID"] = item_id
                self.db.execute("INSERT OR REPLACE INTO items VALUES(?,?,?)", (name, item_id, json.dumps(row)))
                self._remember_id(name,item_id)

    def reset(self):
        from .data_errors import clear
        clear(self)
        self.db.execute("DELETE FROM items")
        self.db.execute('DELETE FROM list_sequences')
        self.db.commit()
