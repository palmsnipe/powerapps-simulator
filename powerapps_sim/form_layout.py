"""Pixel bounds for form cards; authored X/Y remain logical row ordering.

Width and Height properties retain their authored minima. Rendered row height
and WidthFit expansion live separately, so layout never rewrites Power Fx.
"""
import math
from decimal import Decimal
from .syntax import FxError


def number(value, name, nonnegative=False, integer=False):
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)) or not math.isfinite(float(value)):
        raise FxError(f'{name} requires a finite Number', 'Type')
    if nonnegative and value < 0 or integer and (value < 1 or value != int(value)):
        raise FxError(f'{name} requires '+('a positive integer' if integer else 'a nonnegative Number'), 'Validation')
    return float(value)


def validate(ref, name, value):
    if ref.family == 'Form' and name == 'NumberOfColumns':number(value,name,integer=True)
    if ref.family == 'TypedDataCard':
        if name == 'WidthFit' and not isinstance(value,bool):raise FxError('WidthFit requires Boolean','Type')
        if name in ('X','Y','Width','Height'):number(value,name,nonnegative=name in ('Width','Height'))


def bounds(form):
    """Stable row groups, overflow packing, even WidthFit and row stretching."""
    runtime=form.runtime;key=('form',form.path)
    if key in runtime.layout_cache:return runtime.layout_cache[key]
    width=number(form.property('Width'),'Form.Width',nonnegative=True)
    columns=number(form.property('NumberOfColumns'),'NumberOfColumns',integer=True)
    geometry={};issues={};entries=[]
    def read(ref,name,fallback):
        try:return ref.property(name)
        except FxError as error:
            issues.setdefault(ref.path,[]).append(f'{name}: {error.message}')
            return fallback
    for index,card in enumerate(form.children):
        if card.family!='TypedDataCard':continue
        if read(card,'Visible',False) is False:continue
        entries.append((read(card,'Y',0),read(card,'X',0),index,card,
            read(card,'Width',width/columns),read(card,'Height',70),read(card,'WidthFit',False)))
    entries.sort(key=lambda e:e[:3])
    lines=[];line=[];used=0;row=None
    for y,x,index,card,w,h,fit in entries:
        if line and (y!=row or used+w>width+1e-8):lines.append(line);line=[];used=0
        line.append((card,w,h,fit));used+=w;row=y
    if line:lines.append(line)
    def content_bottom(parent):
        bottom=0
        for child in parent.children:
            if read(child,'Visible',False) is False:continue
            nested=content_bottom(child) if child.family=='GroupContainer' else 0
            height=read(child,'Height',0) if child.raw_property('AutoHeight') is not None and read(child,'AutoHeight',False) else 0
            if nested or height:bottom=max(bottom,read(child,'Y',0)+max(nested,height))
        return bottom
    top=0
    for line in lines:
        extra=max(0,width-sum(e[1] for e in line));fitting=sum(bool(e[3]) for e in line)
        height=max(max(h,content_bottom(card)) for card,w,h,fit in line);left=0
        for card,w,h,fit in line:
            size=w+(extra/fitting if fit and fitting else 0)
            geometry[card.path]={'X':left,'Y':top,'Width':size,'Height':height}
            left+=size
        top+=height
    result={'cards':geometry,'errors':issues,'content_height':top,
            'content_width':max([width]+[b['X']+b['Width'] for b in geometry.values()])}
    runtime.layout_cache[key]=result
    return result


def decorate(form,node):
    try:result=bounds(form)
    except FxError as error:
        form.runtime.diagnostic(error,form.control.source,f'{form.name}.Layout')
        node['errors'].append(error.message);return
    node['form_layout']={'content_height':result['content_height'],'content_width':result['content_width']}
    for child in node['children']:
        if child['path'] in result['cards']:child['form_bounds']=result['cards'][child['path']]
        child['errors'].extend(result['errors'].get(child['path'],[]))
    # Render and keyboard traversal follow the same rows, retaining paint order.
    node['children'].sort(key=lambda c:(c.get('form_bounds',{}).get('Y',0),c.get('form_bounds',{}).get('X',0),c.get('paint_order',0)))
