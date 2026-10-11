"""Authored expression locations shared by evaluation, diagnostics and inspection.

Locations are runtime metadata. They never change or enter Power Apps source,
Power Fx records, or exported error records.
"""
from dataclasses import dataclass,replace
from .components import component_definition,validate_kind


@dataclass(frozen=True)
class Expression:
    formula: object
    source: str
    member: str
    owner: str
    line: int | None = None
    folded_positions: tuple = ()

    def line_at(self,offset):
        return self.line+str(self.formula)[:offset].count('\n')+sum(p<offset for p in self.folded_positions) if self.line is not None else None

    def context(self,ctx):
        return replace(ctx,error_source=self.member,formula_origin=self)

    def locate(self,error):
        result=error.located(self.member)
        if not result.end:
            result.start,result.end=0,len(str(self.formula or ''))
            result.span_source=self.member
        if result.expression_origin is None and (not result.span_source or result.span_source==self.member):
            result.expression_origin=self
        return result


def mapped(mapping,key,source,member,owner):
    try:line=(mapping.lc.key(key) if mapping.get(key) is None else mapping.lc.value(key))[0]+1
    except (AttributeError,KeyError,TypeError):
        try:line=mapping.lc.line+1
        except (AttributeError,TypeError):line=None
    value=mapping.get(key)
    if line is not None and getattr(value,'style',None) in ('|','>'):line+=1
    return Expression(value,source,member,owner,line,tuple(getattr(value,'fold_pos',())))


def property_expression(ref,name):
    definition=component_definition(ref.runtime.project,ref.control)
    custom=definition.raw.get('CustomProperties',{}).get(name) if definition else None
    member=ref.path+'.'+name
    # Definition-owned output/action functions cannot be overridden by the host.
    owned=custom and (validate_kind(custom) in ('Output','Action') or
        validate_kind(custom)=='Function' and custom.get('PropertyDefinition',custom.get('Direction','Output'))!='Input'
        and custom.get('PropertyKind')!='InputFunction')
    if owned:
        return mapped(definition.properties,name,definition.source,member,ref.path) if name in definition.properties else mapped(custom,'Default',definition.source,member,ref.path)
    if name in ref.control.properties:return mapped(ref.control.properties,name,ref.control.source,member,ref.path)
    if custom:return mapped(custom,'Default',definition.source,member,ref.path)
    if definition and name in definition.properties:return mapped(definition.properties,name,definition.source,member,ref.path)
    return Expression(ref.raw_property(name),ref.control.source,member,ref.path)


def parameter_expression(ref,name,param,spec):
    definition=component_definition(ref.runtime.project,ref.control)
    return mapped(spec,'Default',definition.source,ref.path+'.'+name+'.'+param+'.Default',ref.path)


def app_expression(runtime,name,member=None):
    return mapped(runtime.project.app,name,runtime.app_source(),member or 'App.'+name,'App')


def authored_property(control,name):
    """Locate what was authored, including an illegal host override.

    Binding must report that override at the host declaration; runtime property
    evaluation still uses definition ownership through property_expression.
    """
    member=control.name+'.'+name
    if name in control.properties:
        return mapped(control.properties,name,control.source,member,control.name)
    custom=control.raw.get('CustomProperties',{}).get(name,{})
    return mapped(custom,'Default',control.source,member,control.name)


def authored_parameter(control,name,param,spec):
    return mapped(spec,'Default',control.source,control.name+'.'+name+'.'+param+'.Default',control.name)


def contract_expression(control,name,error,*,owner=None):
    """Location of a malformed component signature, without evaluating it."""
    custom=control.raw.get('CustomProperties',{}).get(name,{})
    owner=owner or control.name
    param,key=getattr(error,'component_declaration',(None,'PropertyKind'))
    if param is not None:
        for item in custom.get('Parameters',[]):
            if isinstance(item,dict) and param in item:
                return mapped(item[param],key,control.source,owner+'.'+name+'.'+param+'.'+key,owner)
    return mapped(custom,key,control.source,owner+'.'+name+'.'+key,owner)
