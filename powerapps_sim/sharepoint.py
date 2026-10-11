"""Local SharePoint field shapes; no credentials or live connector behavior."""


def item_schema(field):
    return field.get('items', {}) if field.get('type') == 'array' else field


def complex_kind(field, definition, key):
    shape = item_schema(field)
    props = shape.get('properties', {})
    if 'Claims' in props:
        return 'person'
    if key in definition.get('choices', {}) or any(
            s.get('x-ms-capabilities', {}).get('x-ms-sp', {}).get('IsChoice') for s in (field, shape)):
        return 'choice'
    if key in definition.get('lookups', {}) or 'Id' in props:
        return 'lookup'
    return None
