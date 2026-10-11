"""Result boundaries and live row scopes for pure table expressions.

Queries may be rechecked after a source edit. Consumers observe their returned
value, and volatile row formulas observe the fields they actually read. Values
remain ordinary records/tables; behavior execution never uses these boundaries.
"""
from collections import Counter
from hashlib import sha256
from dataclasses import replace
from .reactivity import fingerprint
from .syntax import FxError,call_name

FUNCTIONS=frozenset('Table Filter LookUp Search Sort SortByColumns AddColumns ShowColumns DropColumns RenameColumns GroupBy Ungroup ForAll Concat Distinct Sum Average Min Max Count CountA CountRows CountIf VarP StdevP First Last FirstN LastN Index'.split())


def identity(key):
    """Bound nested scope identities so dependency keys stay small."""
    return sha256(repr(key).encode()).hexdigest()


def rows_keys(rows):
    counts=Counter();keys=[]
    for index,row in enumerate(rows):
        identifier=next((row[name] for name in ('ID','Id') if isinstance(row,dict) and row.get(name) is not None),None)
        identity=('id',fingerprint(identifier)) if identifier is not None else ('position',index)
        occurrence=counts[identity];counts[identity]+=1
        keys.append((*identity,occurrence))
    return keys


def lexical_signature(ctx):
    # Live query/gallery rows carry probes. Plain lexical arguments remain a
    # conservative signature so a function's new argument cannot reuse old data.
    return tuple(('live',frame.probe_key) if getattr(frame,'probe',None) else
                 ('value',fingerprint(dict(frame)),fingerprint(getattr(frame,'sources',{}))) for frame in ctx.frames)


class Input:
    def __init__(self,scope,node,source,rows):
        self.scope,self.node=scope,node
        self.epoch=scope.fx.host.reactive.epoch
        self.rows=rows;self.keys=rows_keys(rows);self.mapping=dict(zip(self.keys,rows))
    def refresh(self):
        fx=self.scope.fx;reactive=fx.host.reactive
        if self.epoch!=reactive.epoch:
            from .fx import table
            with reactive.untracked():rows=table(fx.eval(self.node,self.scope.ctx))
            self.rows=rows;self.keys=rows_keys(rows);self.mapping=dict(zip(self.keys,rows));self.epoch=reactive.epoch
        return self.mapping
    def current(self,key):
        values=self.refresh()
        if key not in values:raise FxError('Query record no longer exists','Validation')
        return values[key]


class Scope:
    def __init__(self,fx,key,ctx):
        self.fx,self.key,self.inputs=fx,key,{}
        self.ctx=replace(ctx,query_scope=self)
    def input(self,node,source,rows):
        key=(node.start,node.end,node.kind)
        if key not in self.inputs:self.inputs[key]=Input(self,node,source,rows)
        return self.inputs[key]


def remember(reactive,key,node,ctx,row_key=None):
    if key in reactive.entries:
        ref=ctx.self_ref or ctx.component_ref
        reactive.metadata[key]={
            'formula':ctx.formula_source[node.start:node.end] or None,
            'source':ctx.formula_origin.source if ctx.formula_origin else ref.control.source if ref else ctx.host.app_source(),
            'line':ctx.formula_origin.line if ctx.formula_origin else None,
            'span':[node.start,node.end],
            'member':ctx.error_source,
            'row_key':fingerprint(row_key) if row_key is not None else None}


def evaluate(fx,node,ctx,loader):
    reactive=fx.host.reactive
    if ctx.behavior or not (reactive.frames or ctx.query_scope):return loader(ctx)
    owner=ctx.self_ref.path if ctx.self_ref else ctx.component_ref.path if ctx.component_ref else ctx.formula_origin.owner if ctx.formula_origin else 'App'
    anchor=(ctx.query_scope.key,tuple(frame.probe_key for frame in ctx.frames if getattr(frame,'probe',None))) if ctx.query_scope else reactive.frames[-1].key
    name=call_name(node.children[0]) if node.kind=='call' else '[]'
    key=('query',owner,name,(node.start,node.end),identity(anchor))
    def load():return loader(replace(ctx,query_scope=Scope(fx,key,ctx)))
    signature=lambda:(repr(node),lexical_signature(ctx))
    # Isolate producer inputs. The caller sees the returned scalar/table,
    # including complete record contents and errors, rather than every read.
    def result():return reactive.unit(key,load,signature)
    try:return reactive.project(('query-result',key),result)
    finally:remember(reactive,key,node,ctx)


def rows(fx,node,source,ctx):
    from .fx import table
    values=table(source)
    if ctx.query_scope and not ctx.behavior:ctx.query_scope.input(node,source,values)
    return values


def row_formula(fx,source,row,formula,ctx,index=None):
    scope=ctx.query_scope;reactive=fx.host.reactive
    if scope is None or ctx.behavior:return fx.eval(formula,fx.row_context(source,row,ctx))
    input_=scope.inputs.get((source.start,source.end,source.kind))
    if input_ is None:return fx.eval(formula,fx.row_context(source,row,ctx))
    row_key=input_.keys[index] if index is not None else next((key for key,value in input_.mapping.items() if value is row),None)
    if row_key is None:return fx.eval(formula,fx.row_context(source,row,ctx))
    key=('query-row',scope.key[1],call_name(formula.children[0]) if formula.kind=='call' else 'row',scope.key,row_key,(formula.start,formula.end))
    probe_key=('query-record',scope.key,row_key)
    def context():
        with reactive.untracked():current=input_.current(row_key);row_ctx=fx.row_context(source,current,ctx)
        frame=row_ctx.frames[-1]
        def probe(name):
            with reactive.untracked():fresh=fx.row_context(source,input_.current(row_key),ctx).frames[-1]
            return fresh[name]
        frame.probe=probe;frame.probe_key=probe_key
        previous=next((getattr(f,'source_probes',{}) for f in reversed(ctx.frames) if getattr(f,'source_probes',None)),{})
        source_name=call_name(source.children[0] if source.kind=='alias' else source)
        frame.source_probes={**previous,**({source_name:(lambda:input_.current(row_key),probe_key)} if source_name else {})}
        return row_ctx
    def load():
        reactive.leaf(('query-row-present',scope.key,row_key),lambda:row_key in input_.refresh(),isolated=True)
        return fx.eval(formula,context())
    try:return reactive.unit(key,load,lambda:(repr(formula),lexical_signature(ctx)))
    finally:remember(reactive,key,formula,ctx,row_key)
