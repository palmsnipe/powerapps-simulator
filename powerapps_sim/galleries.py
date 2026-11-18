"""Gallery row identity and presentation metadata, separate from source records."""
from functools import lru_cache
import hashlib
import json
from .tables import SourceRecord
from .fx import table
from .syntax import FxError


class GalleryRecord(SourceRecord):
    def __init__(self, row, gallery, key):
        super().__init__(row, getattr(row, 'logical_names', {}),
                         getattr(row, 'source_name', None), getattr(row, 'defaults_for', None))
        self.gallery, self.key = gallery, key

    def copy(self):
        return self.gallery_derivative(dict(self))

    def gallery_derivative(self, fields):
        result = GalleryRecord(fields, self.gallery, self.key)
        result.logical_names = self.logical_names
        result.source_name, result.defaults_for = self.source_name, self.defaults_for
        return result

    def gallery_member(self, name):
        if name == 'IsSelected':
            return selected(self.gallery)[0] == self.key
        raise KeyError(name)


def digest_of(value):
    from .runtime import serial
    return hashlib.sha256(json.dumps(serial(value), sort_keys=True, ensure_ascii=False).encode()).hexdigest()


@lru_cache(maxsize=8192, typed=True)
def scalar_id_digest(field, value):
    return digest_of({field: value})[:16]


def row_digest(row):
    if isinstance(row, dict):
        for field in ('ID', 'Id'):
            value = row.get(field)
            if value is not None:
                if type(value) in (str, int):
                    return scalar_id_digest(field, value)
                return digest_of({field: value})[:16]
    return digest_of(row)[:16]


class GalleryItems:
    def __init__(self, ref):
        self.items = table(ref.property('Items'))
        self.rows = []
        self.indices = {}
        self.digest = None
        self.all_records = True
        counts = {}
        for row in self.items:
            digest = row_digest(row)
            occurrence = counts.get(digest, 0)
            counts[digest] = occurrence + 1
            key = f'{digest}:{occurrence}'
            self.indices[key] = len(self.rows)
            if isinstance(row, dict):
                row = GalleryRecord(row, ref, key)
            else:
                self.all_records = False
            self.rows.append((key, row))


def items_snapshot(ref):
    cache = ref.runtime.gallery_rows_cache
    if ref.path not in cache:
        cache[ref.path] = GalleryItems(ref)
    return cache[ref.path]


def keyed_rows(ref):
    return items_snapshot(ref).rows


def selected(ref):
    items = items_snapshot(ref)
    rows = items.rows
    if 'Selected' in ref.state:
        chosen, key = ref.state['Selected'], ref.state.get('gallery_key')
        index = items.indices.get(key)
        match = rows[index] if index is not None and ref.runtime.same_item(rows[index][1], chosen) else None
        if match is None:
            match = next(((k, row) for k, row in rows if ref.runtime.same_item(row, chosen)), None)
        if match:
            ref.state.update(Selected=match[1], gallery_key=match[0])
            return match
        ref.state.pop('Selected', None)
        ref.state.pop('gallery_key', None)
    default = ref.property('Default')
    first = rows[0] if rows else (None, None)
    if default is None and items.all_records:
        return first
    return next(((k, row) for k, row in rows if ref.runtime.same_item(row, default)), first)


def choose(ref, key, interactive=False):
    if interactive and not ref.property('Selectable'):
        return
    items = items_snapshot(ref)
    index = items.indices.get(key)
    match = items.rows[index][1] if index is not None else None
    if match is None:
        raise ValueError('Gallery row no longer exists; refresh the preview')
    if isinstance(match, FxError):
        raise match
    ref.state.update(Selected=match, gallery_key=key)
    ref.runtime.invalidate()


def token(ref):
    items = items_snapshot(ref)
    if items.digest is None:
        items.digest = digest_of(items.items)
    return f'{ref.runtime.text_generation}:{ref.path}:{ref.runtime.selector_resets.get(ref.path, 0)}:{items.digest}'


def implicit_select(ref):
    from .controls import SUPPORTED
    if ref.control.version not in SUPPORTED.get(ref.family, set()) or ref.family in (
            'Text', 'Screen', 'Form', 'TypedDataCard', 'CanvasComponent', 'Component', 'ModernProgressBar', 'ModernSpinner', 'ModernIcon', 'RichTextEditor'):
        return False
    for ancestor in ref.runtime.ancestors(ref):
        if ancestor.family in ('CanvasComponent', 'Component'):
            return False
        if ancestor.family == 'Gallery':
            return True
    return False


def template_controls(control):
    """Controls in one template; nested galleries own their inner templates."""
    for child in control.children:
        yield child
        if child.family not in ('Gallery', 'CanvasComponent', 'Component'):
            yield from template_controls(child)



def item_alias(runtime, control):
    """Only an outer As on Gallery.Items names that gallery's template record."""
    raw=control.properties.get('Items')
    if not isinstance(raw,str) or not raw.startswith('='):return None
    try:node=runtime.fx.parse(raw)
    except FxError:return None
    return node.children[1].value if node.kind=='alias' and node.children[1].kind=='name' else None


def row_frames(ref,row):
    frame={'ThisRecord':row}
    alias=item_alias(ref.runtime,ref.control)
    if alias:frame[alias]=row
    return [*ref.frames,frame]

def materialize(ref):
    """Build row scopes without evaluating properties or running any events."""
    runtime = ref.runtime
    result = []
    from .gallery_loading import loaded_rows
    live_keys = items_snapshot(ref).indices
    for key, row in loaded_rows(ref):
        row_path = f'{ref.path}/row:{key}'
        if isinstance(row, FxError):
            result.append((key, row, []))
            continue
        scope, children = dict(ref.scope), []
        frames=row_frames(ref,row)
        refreshed=False
        for control in ref.control.children:
            path = f'{row_path}/{control.name}'
            child = runtime.refs.get(path)
            if child:
                from .runtime import serial
                refreshed |= (child.item is not row and serial(child.item) != serial(row)
                              or serial(child.frames) != serial(frames))
            else:child=runtime.build(control, path, ref, row, frames, scope, ref.component)
            child.item, child.frames = row, frames
            scope[control.name] = child
            children.append(child)
        for child in children:
            for nested in [child, *runtime.descendants(child)]:
                if next((a for a in runtime.ancestors(nested) if a.family == 'Gallery'), None) is ref:
                    nested.item, nested.frames = row, frames
                    if nested.component is ref.component:
                        scope[nested.name] = nested
                        nested.scope = scope
        if refreshed:
            # Pre-render lifecycle checks may have cached inputs using the old
            # row. Invalidate dependent rules after refreshing every scope, but
            # retain this materialization's consistent Items snapshot.
            runtime.property_cache.clear();runtime.formula_cache.clear();runtime.layout_cache.clear()
        result.append((key, row, children))
    prefix = ref.path + '/row:'
    for path in list(runtime.refs):
        if path.startswith(prefix) and path[len(prefix):].split('/', 1)[0] not in live_keys:
            runtime.gallery_loading.pop(path, None)
            runtime.refs.pop(path, None)
            runtime.control_state.pop(path, None)
            runtime.input_baselines.pop(path, None)
    return result


def all_items(ref):
    result = []
    for key, row, children in materialize(ref):
        if isinstance(row, FxError) or row is None:
            result.append(row)
            continue
        if not isinstance(row, dict):
            raise FxError('Gallery AllItems requires record rows', 'Type')
        fields = dict(row)
        aliases = set(getattr(row, 'logical_names', {}).values())
        for child in children:
            for control in [child, *ref.runtime.descendants(child)]:
                if next((a for a in ref.runtime.ancestors(control) if a.family == 'Gallery'), None) is not ref:
                    continue
                if control.component is not ref.component:
                    continue
                if control.name in fields or control.name in aliases:
                    raise FxError(f'Gallery AllItems control {control.name} conflicts with an item field', 'Unsupported')
                fields[control.name] = control
        result.append(row.gallery_derivative(fields) if isinstance(row, GalleryRecord) else fields)
    return result


def all_items_type(binder, control):
    from dataclasses import replace
    from .binding import FxType, OPEN_RECORD, BOOLEAN, tabular
    row = binder.property_type(control, 'Items').row or OPEN_RECORD
    fields = dict(row.fields)
    for child in template_controls(control):
        if child.name in fields or child.name in row.aliases:
            raise FxError(f'Gallery AllItems control {child.name} conflicts with an item field', 'Unsupported')
        fields[child.name] = FxType('Control', name=child.name, control=child)
    return tabular(replace(row, fields=fields, virtual={'IsSelected': BOOLEAN}))
