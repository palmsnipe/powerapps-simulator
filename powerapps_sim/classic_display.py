"""Audited classic label/shape contracts; server-owned approximate geometry."""
from functools import lru_cache
from pathlib import Path
from decimal import Decimal
import json,math
from .syntax import FxError

FAMILIES=frozenset(('Label','Rectangle','Circle','Star'))
SHAPES=FAMILIES-{'Label'}
@lru_cache(maxsize=1)
def catalog():return json.loads((Path(__file__).parent/'static/classic-display.json').read_text())
VERSIONS={f:frozenset(v) for f,v in catalog()['families'].items()}
ENUMS={'Align':('Left','Center','Right','Justify'),'VerticalAlign':('Top','Middle','Bottom'),
 'BorderStyle':('Solid','Dashed','Dotted','None'),'FontWeight':('Normal','Bold','Semibold','Lighter'),
 'Live':('Off','Polite','Assertive'),'Overflow':('Hidden','Scroll'),'Role':('Default','Heading1','Heading2','Heading3','Heading4')}
SHAPE_TYPES={**{p:'Color' for p in ('Fill','DisabledFill','HoverFill','PressedFill','BorderColor','FocusedBorderColor')},
 **{p:'Number' for p in ('Width','Height','BorderThickness','FocusedBorderThickness','TabIndex')},'BorderStyle':'Text','PreserveAspectRatio':'Boolean'}
LABEL_TYPES={**SHAPE_TYPES,**{p:'Color' for p in ('Color','DisabledColor','HoverColor','PressedColor','DisabledBorderColor','HoverBorderColor','PressedBorderColor')},
 **{p:'Number' for p in ('Size','LineHeight','PaddingTop','PaddingBottom','PaddingLeft','PaddingRight')},
 **{p:'Boolean' for p in ('AutoHeight','Wrap','Italic','Underline','Strikethrough','IsErrorMessage')},
 **{p:'Text' for p in ('Text','Font','FontWeight','Align','VerticalAlign','Live','Overflow','Role')}}
LABEL_TYPES.pop('PreserveAspectRatio')
TYPES={f:LABEL_TYPES if f=='Label' else SHAPE_TYPES for f in FAMILIES}
FALLBACK={'BorderStyle':'=BorderStyle.Solid','BorderThickness':'=0','FocusedBorderThickness':'=0'}
LABEL_FALLBACK={'Text':'=""','Fill':'=Color.Transparent','BorderColor':'=Color.Black','Align':'=Align.Left',
 'FontWeight':'=FontWeight.Normal','Italic':'=false','Underline':'=false','Strikethrough':'=false','Role':'=TextRole.Default'}
def defaults(family):
 version=max(VERSIONS[family],key=lambda v:tuple(map(int,v.split('.'))))
 return {**FALLBACK,**(LABEL_FALLBACK if family=='Label' else {}),**catalog()['families'][family][version]['defaults']}

def default(ref,name):
 spec=catalog()['families'][ref.family].get(ref.control.version,{})
 profile=ref.runtime.project.config.get('form_factor')
 return spec.get('variants',{}).get(profile,{}).get(name,spec.get('defaults',{}).get(name))

def properties(control):
 """Public native members, plus the simulator's shared automatic-layout contract."""
 if control.version not in VERSIONS[control.family]:return set()
 allowed=set(catalog()['families'][control.family][control.version]['properties'])
 allowed|={'LayoutMinWidth','LayoutMinHeight','LayoutMaxWidth','LayoutMaxHeight','FillPortions','AlignInContainer'}
 return allowed

def errors(control):
 if control.version not in VERSIONS[control.family]:return {'Version':f'Unsupported {control.kind} version'}
 allowed=properties(control)
 result={name:f'{control.kind} has no authored {name} property' for name in control.properties if name not in allowed}
 variant=control.raw.get('Variant','')
 if variant and (control.family!='Star' or variant not in ('star6','star8','star12')):
  result['Variant']=f'Unsupported {control.family} variant {variant}'
 return result

def validate(ref,name,value,actual=None):
 kind=TYPES[ref.family].get(name)
 if name in ENUMS and value is not None and value not in ENUMS[name]:raise FxError(f'{ref.family}.{name} requires '+', '.join(ENUMS[name]),'Type')
 if kind=='Number' and value is not None:
  if isinstance(value,bool) or not isinstance(value,(int,float,Decimal)) or not math.isfinite(float(value)):raise FxError(f'{ref.family}.{name} requires a finite Number','Type')
  if name=='TabIndex' and value!=int(value):raise FxError('TabIndex requires an integer','Type')
  if name!='TabIndex' and value<0:raise FxError(f'{ref.family}.{name} cannot be negative','Validation')
 if kind=='Boolean' and value is not None and not isinstance(value,bool):raise FxError(f'{ref.family}.{name} requires Boolean','Type')
 if kind=='Color' and value is not None and (not isinstance(value,str) or actual and actual.kind not in ('Color','Blank','Unknown','Error')):raise FxError(f'{ref.family}.{name} requires Color','Type')
 if name=='Font' and value is not None and not isinstance(value,str):raise FxError('Label.Font requires Text','Type')
 if name=='IsErrorMessage' and value:raise FxError('Deprecated IsErrorMessage behavior is unverified; configure Live explicitly','Unsupported')

def auto_height(ref):
 """Approximate font measurement; hidden labels retain their last visible height."""
 r=ref.runtime
 if any(a.property('Visible') is False for a in (ref,*r.ancestors(ref))):
  return r.label_heights[ref.path] if ref.path in r.label_heights else ref.eval_raw('Height')
 caption=r.fx.to_text(ref.property('Text'))
 padding=(ref.property('PaddingTop') or 0)+(ref.property('PaddingBottom') or 0)
 size=float(ref.property('Size') or 0);leading=float(ref.property('LineHeight') or 0)
 width=max(1,(ref.property('Width') or 0)-(ref.property('PaddingLeft') or 0)-(ref.property('PaddingRight') or 0))
 chars=max(1,int(float(width)/max(1,size*.55)))
 lines=sum(max(1,math.ceil(len(line)/chars)) for line in caption.split('\n')) if ref.property('Wrap') else 1
 height=math.ceil(lines*size*leading+padding) if caption else padding
 r.label_heights[ref.path]=height
 return height

def render(ref,node):
 if ref.family=='Label':
  p=node['props'];role=p.get('Role') or 'Default';live=p.get('Live') or 'Off'
  node['classic_display']={'heading':int(role[-1]) if role.startswith('Heading') else None,'live':live.lower(),
   'scroll':bool(p.get('Wrap') and p.get('Overflow')=='Scroll' and not p.get('AutoHeight'))}
  return
 p=node['props'];w=max(0,p.get('Width') or 0);h=max(0,p.get('Height') or 0);thickness=p.get('BorderThickness') or 0
 if p.get('BorderStyle')=='None':thickness=0
 inset=min(thickness/2,w/2,h/2);iw=max(0,w-2*inset);ih=max(0,h-2*inset)
 geometry={'viewbox':[0,0,w,h],'stroke_width':thickness,'dash':{'Dashed':[3*thickness,2*thickness],'Dotted':[thickness,thickness]}.get(p.get('BorderStyle'),[])}
 if ref.family=='Rectangle':geometry.update(tag='rect',attributes={'x':inset,'y':inset,'width':iw,'height':ih})
 elif ref.family=='Circle':geometry.update(tag='ellipse',attributes={'cx':w/2,'cy':h/2,'rx':iw/2,'ry':ih/2})
 else:
  count={'star6':6,'star8':8,'star12':12}.get(ref.control.raw.get('Variant'),5)
  points=[]
  for i in range(2*count):
   angle=-math.pi/2+i*math.pi/count;ratio=1 if i%2==0 else .45
   points.append([w/2+iw/2*ratio*math.cos(angle),h/2+ih/2*ratio*math.sin(angle)])
  geometry.update(tag='polygon',points=points)
 node['classic_display']={'geometry':geometry}
