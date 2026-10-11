"""Viewport-driven gallery rows; loading is presentation state, never app behavior."""
from dataclasses import dataclass,field
import hashlib,json,math
from decimal import Decimal
from .syntax import FxError


@dataclass
class Loading:
    keys: set = field(default_factory=set)
    ready: bool = False
    offset: float = 0
    extent: float | None = None


def number(value,name,minimum=0,whole=False):
    if isinstance(value,bool) or not isinstance(value,(int,float,Decimal)) or not math.isfinite(float(value)) or value<minimum or whole and value!=int(value):
        raise FxError(f'Gallery {name} requires a finite '+('whole number' if whole else 'number')+f' >= {minimum}','Type')
    return float(value)


def geometry(ref):
    horizontal=ref.control.raw.get('Variant')=='Horizontal'
    axis=number(ref.property('Width' if horizontal else 'Height'),'extent')
    cross=number(ref.property('Height' if horizontal else 'Width'),'cross extent')
    size=max(1,number(ref.property('TemplateSize'),'TemplateSize'))
    gap=number(ref.property('TemplatePadding'),'TemplatePadding')
    wrap=int(number(ref.property('WrapCount'),'WrapCount',1,True))
    extent=min(axis,ref.runtime.viewport['width' if horizontal else 'height'])
    if cross==0:extent=0
    return {'horizontal':horizontal,'axis':axis,'cross':cross,'extent':extent,'size':size,'gap':gap,'pitch':size+gap,'wrap':wrap}


def window(total,g,offset,extent):
    if extent<=0 or total==0:return 0,0
    groups=math.ceil(extent/g['pitch'])
    first=max(0,math.floor(offset/g['pitch'])-groups)*g['wrap']
    end=(math.ceil((offset+extent)/g['pitch'])+groups)*g['wrap']
    return min(total,first),min(total,end)


def sync(ref):
    active=ref.runtime.gallery_syncing
    if ref.path in active:raise FxError('Gallery loading depends on its own loaded rows','Cycle')
    active.add(ref.path)
    try:return _sync(ref)
    finally:active.remove(ref.path)


def _sync(ref):
    from .galleries import keyed_rows
    rows=keyed_rows(ref);g=geometry(ref)
    delayed=ref.property('DelayItemLoading')
    if not isinstance(delayed,bool):raise FxError('Gallery DelayItemLoading requires a Boolean','Type')
    if ref.path not in ref.runtime.gallery_loading:
        ref.runtime.gallery_loading[ref.path]=Loading(ready=not delayed)
    state=ref.runtime.gallery_loading[ref.path]
    state.keys.intersection_update(key for key,_ in rows)
    extent=g['extent'] if state.extent is None else min(state.extent,g['axis'])
    length=max(0,math.ceil(len(rows)/g['wrap'])*g['pitch']-g['gap'])
    state.offset=min(state.offset,max(0,length-extent))
    start,end=window(len(rows),g,state.offset,extent)
    if state.ready:state.keys.update(key for key,_ in rows[start:end])
    return state,rows,g,start,end,length


def loaded_rows(ref):
    state,rows,*_=sync(ref)
    return [(key,row) for key,row in rows if key in state.keys]


def count(ref):return len(sync(ref)[0].keys)


def token(ref):
    from .galleries import token as item_token
    g=geometry(ref)
    digest=hashlib.sha256(json.dumps(g,sort_keys=True).encode()).hexdigest()
    return item_token(ref)+':'+digest


def metadata(ref):
    state,rows,g,start,end,length=sync(ref)
    return {'total':len(rows),'loaded':len(state.keys),'start':start,'end':end,'length':length,
            'waiting':not state.ready,'viewport_token':token(ref),'retained_keys':sorted(state.keys)}


def viewport(ref,value):
    if not isinstance(value,dict) or set(value)!={'offset','extent','viewport_token'}:
        raise ValueError('Gallery viewport requires offset, extent and viewport_token')
    try:
        offset=number(value['offset'],'scroll offset')
        extent=number(value['extent'],'visible extent')
    except FxError as error:raise ValueError(error.message) from None
    if value['viewport_token']!=token(ref):return False
    state,_,g,*_=sync(ref)
    if extent>g['axis']+1:raise ValueError('Gallery visible extent exceeds its source dimensions')
    if extent==0:return False
    previous=(state.ready,state.offset,state.extent,len(state.keys))
    state.ready,state.offset,state.extent=True,offset,min(extent,g['axis'])
    sync(ref)
    changed=previous!=(state.ready,state.offset,state.extent,len(state.keys))
    if changed:
        runtime=ref.runtime
        if previous[1]!=state.offset and runtime.started and not runtime.preview_screen and not runtime.preview_component:
            # Canvas documents that classic ComboBox selection is not retained
            # in scrolling galleries. The simulator resets on a changed offset.
            for child in list(runtime.refs.values()):
                if child.family=='Classic/ComboBox' and child.path.startswith(ref.path+'/row:'):
                    runtime.clear_control_state(child)
        runtime.invalidate()
    return changed


def ensure(ref,index):
    state,rows,*_=sync(ref)
    state.keys.add(rows[index][0])
