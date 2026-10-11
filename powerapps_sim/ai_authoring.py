"""Focused, saved-source discovery and revision-checked control edits.

These helpers never render the live runtime. Edits are staged through the same
validation, migration and undo service as full-document changes.
"""
from copy import deepcopy
import re

from ruamel.yaml.scalarstring import LiteralScalarString

from .controls import SUPPORTED, INSPECT_OUTPUTS, contract_errors
from .source import Project, dump_yaml, yaml_engine


def control_path(control):
    parts = []
    while control:
        parts.append(control.name)
        control = control.parent
    return '/'.join(reversed(parts))


def controls(project):
    return [c for group in project.controls.values() for c in group]


def resolve(project, path, source=None):
    if not isinstance(path, str) or not path:
        raise ValueError('Provide a saved-source control path from read_controls')
    if source is not None and (not isinstance(source, str) or source not in project.documents):
        raise ValueError('Source document not found')
    matches = [c for c in controls(project) if control_path(c) == path and (source is None or c.source == source)]
    if not matches:
        raise ValueError(f'Control path not found: {path}')
    if len(matches) != 1:
        raise ValueError('Control path is ambiguous; provide its source document')
    return matches[0]


def location(mapping, key=None):
    lc = getattr(mapping, 'lc', None)
    if lc is None:
        return None
    if key is not None:
        mark = lc.key(key)
        return mark[0] + 1 if mark else None
    return lc.line + 1 if lc.line is not None else None


def describe(control):
    return {'path': control_path(control), 'name': control.name, 'kind': control.kind,
            'source': control.source, 'line': location(control.raw),
            'parent': control_path(control.parent) if control.parent else None,
            'children': [control_path(c) for c in control.children]}


def read_controls(project, query='', source=None, offset=0, limit=50, include_properties=False):
    if not isinstance(query, str) or len(query) > 1000:
        raise ValueError('Query must be text under 1000 characters')
    if source is not None and (not isinstance(source, str) or source not in project.documents):
        raise ValueError('Source document not found')
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 500:
        raise ValueError('Use a nonnegative offset and a limit between 1 and 500')
    if type(include_properties) is not bool:
        raise ValueError('include_properties must be Boolean')
    query = query.casefold()
    found = []
    for c in controls(project):
        if source is not None and c.source != source:
            continue
        matching = {k: str(v) for k, v in c.properties.items() if query and
                    query in (str(k) + ' ' + str(v)).casefold()}
        if query and not matching and query not in (control_path(c) + ' ' + c.kind + ' ' + c.source).casefold():
            continue
        row = describe(c)
        row['matching_properties'] = matching
        if include_properties:
            row['properties'] = dict(c.properties)
        found.append(row)
    found.sort(key=lambda c: (c['source'], c['path']))
    return {'controls': found[offset:offset + limit], 'total': len(found), 'offset': offset,
            'next_offset': offset + limit if offset + limit < len(found) else None,
            'source_errors': project.source_errors}


def read_control(project, path, source=None):
    c = resolve(project, path, source)
    versions = sorted(SUPPORTED.get(c.family, ()))
    component = project.components.get(c.raw.get('ComponentName')) if c.family == 'CanvasComponent' else c if c.family == 'Component' else None
    return {**describe(c), 'definition': {k: v for k, v in c.raw.items() if k != 'Children'},
            'property_lines': {k: location(c.properties, k) for k in c.properties},
            'contract': {'supported': c.version in versions, 'supported_versions': versions,
                         'outputs': list(INSPECT_OUTPUTS.get(c.family, ())),
                         'findings': contract_errors(c),
                         'custom_properties': component.raw.get('CustomProperties', {}) if component else {},
                         'note': 'Local simulator contract; authored properties are formulas, not evaluated values. Defaults and runtime timing depend on the control version and context.'}}


def _name(value, label):
    if not isinstance(value, str) or not re.fullmatch(r'[^/\s]+', value):
        raise ValueError(f'{label} must be nonempty text without whitespace or slashes')
    return value


def _validate_control(name, raw, known):
    _name(name, 'Control name')
    if name in known:
        raise ValueError(f'Duplicate control name: {name}')
    known.add(name)
    if not isinstance(raw, dict) or not isinstance(raw.get('Control'), str) or not raw['Control']:
        raise ValueError('New controls need a Control family/version')
    if not isinstance(raw.get('Properties', {}), dict):
        raise ValueError('Control Properties must be an object')
    for key, value in raw.get('Properties', {}).items():
        _name(key, 'Property name')
        if not isinstance(value, str) or not value.startswith('='):
            raise ValueError('Property values must be Power Fx text starting with =')
    if not isinstance(raw.get('Children', []), list):
        raise ValueError('Control Children must be a list')
    for child in raw.get('Children', []):
        if not isinstance(child, dict) or len(child) != 1:
            raise ValueError('Children must contain single named-control objects')
        child_name, child_raw = next(iter(child.items()))
        _validate_control(child_name, child_raw, known)


def edit_sources(project, edits):
    if not isinstance(edits, list) or not 1 <= len(edits) <= 100:
        raise ValueError('Provide between 1 and 100 control edits')
    changed = set()
    for edit in edits:
        if not isinstance(edit, dict):
            raise ValueError('Each edit must be an object')
        op = edit.get('op')
        fields = {'set_property': {'op', 'path', 'source', 'property', 'value'},
                  'remove_property': {'op', 'path', 'source', 'property'},
                  'add_control': {'op', 'parent', 'source', 'name', 'control', 'index'}}
        if not isinstance(op, str) or op not in fields or set(edit) - fields[op]:
            raise ValueError('Use set_property, remove_property or add_control with documented fields')
        c = resolve(project, edit.get('parent') if op == 'add_control' else edit.get('path'), edit.get('source'))
        if op == 'add_control':
            # Synthetic scratch roots have no authored node to receive children.
            if c.kind == 'Screen' and not any(c.raw is raw for raw in project.parsed[c.source].get('Screens', {}).values()):
                raise ValueError('Add to an authored control, not a synthetic scratch screen')
            raw = deepcopy(edit.get('control'))
            name = edit.get('name')
            _validate_control(name, raw, set(project.controls))
            children = c.raw.setdefault('Children', [])
            index = edit.get('index', len(children))
            if type(index) is not int or not 0 <= index <= len(children):
                raise ValueError('index must be an integer within the parent Children list')
            children.insert(index, {name: raw})
            c.children.insert(index, project._control(name, raw, c.source, c))
        else:
            prop = _name(edit.get('property'), 'Property name')
            props = c.raw.setdefault('Properties', {})
            if op == 'remove_property':
                if prop not in props:
                    raise ValueError(f'Authored property not found: {prop}')
                del props[prop]
            else:
                value = edit.get('value')
                if not isinstance(value, str) or not value.startswith('=') or len(value) > 100_000:
                    raise ValueError('value must be Power Fx text starting with =, under 100,000 characters')
                props[prop] = LiteralScalarString(value) if '\n' in value else value
        changed.add(c.source)
    result = {}
    for source in sorted(changed):
        data = project.parsed[source]
        # Keep clipboard documents in their original sequence form.
        if isinstance(yaml_engine().load(project.documents[source]), list):
            data = data['Screens']['Scratch']['Children']
        text = dump_yaml(data)
        if text != project.documents[source]:
            result[source] = text
    if not result:
        raise ValueError('Edits do not change the saved source')
    return result
