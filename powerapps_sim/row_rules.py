"""Stable row formula boundaries for grid, gallery and selector render helpers."""
from dataclasses import replace
from .syntax import FxError


def row_map(parent,gallery=False):
    runtime=parent.runtime
    key=(parent.path,'__row_inputs__',gallery)
    if key not in runtime.property_cache:
        if gallery:
            from .galleries import keyed_rows
            rows=keyed_rows(parent)
        else:
            from .fx import table
            from .data_table import row_keys
            values=table(parent.property('Items'))
            rows=zip(row_keys(values),values)
        runtime.property_cache[key]=dict(rows)
    return runtime.property_cache[key]


def row_key(parent,row,gallery=False):
    rows=row_map(parent,gallery)
    return next((key for key,value in rows.items() if value is row),
        next((key for key,value in rows.items() if value==row),None))


def evaluate(ref,name,row,key,loader,parent=None,gallery=False):
    parent=parent or ref
    runtime=ref.runtime
    if key is None:
        # Empty selected output is a separate context, not another row's cache.
        return loader(replace(ref.context(),item=row,item_probe=None,item_key=None))
    def current():
        values=row_map(parent,gallery)
        if key not in values:raise FxError('Rendered record no longer exists','Validation')
        value=values[key]
        if isinstance(value,FxError):raise value
        return value
    def load():
        # Establish lifetime by identity, without making an unused ThisItem a
        # dependency. The evaluator observes the live record when it is read.
        runtime.reactive.leaf(('row-present',parent.path,key),lambda:key in row_map(parent,gallery),isolated=True)
        with runtime.reactive.untracked():item=current();ctx=ref.context()
        if gallery:
            from .galleries import row_frames
            ctx=replace(ctx,frames=row_frames(ref,item))
        ctx=replace(ctx,item=item,item_probe=current,item_key=('row-input',parent.path,key),error_source=ref.path+'.'+name)
        return loader(ctx)
    return runtime.reactive.unit(('row',ref.path,name,key),load,
        lambda:repr(ref.raw_property(name)))


def gallery_formula(ref,name,row,key):
    def load(ctx):
        raw=ref.raw_property(name)
        return ref.runtime.fx.evaluate(raw,ctx) if isinstance(raw,str) and raw.startswith('=') else raw
    return evaluate(ref,name,row,key,load,gallery=True)


def item_formula(ref,name,row,key=None):
    if key is None:key=row_key(ref,row)
    def load(ctx):
        raw=ref.raw_property(name)
        return ref.runtime.fx.evaluate(raw,ctx) if isinstance(raw,str) and raw.startswith('=') else raw
    return evaluate(ref,name,row,key,load)
