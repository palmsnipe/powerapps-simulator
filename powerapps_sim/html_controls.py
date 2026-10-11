"""Offline HTML text presentation. Source is retained; removed behavior is diagnosed.

Only a local presentation fragment reaches the browser. The HTML layout estimate
is deterministic for headless workflows; it does not claim browser pixel parity.
"""
from html.parser import HTMLParser
from html import escape
from urllib.parse import urlsplit, unquote
from functools import lru_cache
from decimal import Decimal
import math,re
from .syntax import FxError

VERSIONS = {'2.0.0', '2.1.0'}
# Explicit 2.0.0 template defaults recovered from Microsoft's shipped
# AccountPlanReviewerMaster/Marc2PowerPlatformDevOpsAlm archives. The documented
# 2.1.0 HTML contract uses these shared defaults; theme/font fallbacks are common.
DEFAULTS = {'HtmlText':'=""', 'AutoHeight':'=false', 'Width':'=200', 'Height':'=40',
    'PaddingTop':'=5','PaddingRight':'=5','PaddingBottom':'=5','PaddingLeft':'=5',
    'BorderColor':'=Color.Black', 'Fill':'=RGBA(255,255,255,0)', 'DisabledFill':'=RGBA(119,119,119,.4)',
    'DisabledBorderColor':'=RGBA(56,56,56,1)', 'HoverBorderColor':'=Self.BorderColor',
    'PressedBorderColor':'=Self.BorderColor','BorderStyle':'=BorderStyle.None'}
TYPES = {**{p:'Number' for p in ('X','Y','Width','Height','Size','BorderThickness','PaddingTop','PaddingRight','PaddingBottom','PaddingLeft')},
    **{p:'Color' for p in ('Fill','Color','BorderColor','DisabledFill','DisabledBorderColor','HoverBorderColor')},
    'HtmlText':'Text','AutoHeight':'Boolean'}
TAGS = frozenset('a abbr b bdi bdo blockquote br caption code col colgroup dd del div dl dt em h1 h2 h3 h4 h5 h6 hr i img ins kbd li mark ol p pre q s samp small span strong sub sup table tbody td tfoot th thead tr u ul var'.split())
VOID = frozenset(('br','hr','img','col'))
DROP_CONTENT = frozenset(('script','style','iframe','object','embed','svg','math','template','noscript'))
BLOCKS = frozenset('blockquote dd div dl dt h1 h2 h3 h4 h5 h6 hr li ol p pre table tr ul'.split())
CSS = frozenset('color background-color font-family font-size font-weight font-style line-height letter-spacing text-align text-decoration text-decoration-line text-decoration-color text-decoration-style text-decoration-thickness text-transform white-space word-break overflow-wrap display position top right bottom left width height min-width max-width min-height max-height padding padding-top padding-right padding-bottom padding-left margin margin-top margin-right margin-bottom margin-left margin-block-start margin-block-end margin-inline-start margin-inline-end padding-inline-start border border-width border-style border-color border-radius border-collapse border-spacing vertical-align list-style-type list-style-position opacity overflow overflow-x overflow-y box-sizing gap row-gap column-gap flex flex-direction flex-wrap flex-grow flex-shrink flex-basis align-items align-self justify-content'.split())


def validate(name,value):
    kind=TYPES.get(name)
    if kind=='Boolean' and not isinstance(value,bool):raise FxError(f'HtmlViewer.{name} requires a Boolean','Type')
    if kind=='Text' and value is not None and not isinstance(value,str):raise FxError(f'HtmlViewer.{name} requires Text','Type')
    if kind=='Number':
        if isinstance(value,bool) or not isinstance(value,(int,float,Decimal)) or not math.isfinite(float(value)):raise FxError(f'HtmlViewer.{name} requires a finite Number','Type')
        if name not in ('X','Y') and value<0:raise FxError(f'HtmlViewer.{name} cannot be negative','Validation')


def styles(source,issues):
    result={}
    for part in source.split(';'):
        if not part.strip():continue
        key,sep,value=part.partition(':');key=key.strip().lower();value=value.strip()
        if not sep or key not in CSS or not value or re.search(r'url\s*\(|expression|[\\@{}<>]|/\*|!important',value,re.I):
            issues.add(f'HTML style {key or "declaration"} is unsupported');continue
        if key=='position' and value not in ('static','relative','absolute'):
            issues.add(f'HTML position {value} is unsupported');continue
        result[key]=value
    return result


class Fragment(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.output=[];self.issues=set();self.stack=[];self.dropped=[]
        self.root={'tag':'root','styles':{},'attrs':{},'children':[]};self.nodes=[self.root]
    def handle_starttag(self,tag,attrs):
        if self.dropped:
            if tag in DROP_CONTENT:self.dropped.append(tag)
            return
        if tag in DROP_CONTENT:
            self.issues.add(f'HTML <{tag}> content is unsupported');self.dropped.append(tag);return
        if len(self.stack) >= 64:
            self.issues.add('HTML nesting beyond 64 elements is unsupported');return
        if tag not in TAGS:
            self.issues.add(f'HTML <{tag}> is unsupported');return
        clean={};css={}
        for name,value in attrs:
            value=value or ''
            if name=='style':css=styles(value,self.issues);clean[name]=';'.join(k+':'+v for k,v in css.items())
            elif name in ('title','lang','dir','id','class','aria-label','role') or tag in ('td','th') and name in ('colspan','rowspan') or tag in ('ol','li') and name in ('start','value') or tag=='img' and name in ('alt','width','height'):
                clean[name]=value
            elif tag=='a' and name=='href':
                clean['data-emu-link']=value
                if value.startswith('#'):clean['href']=value
                else:self.issues.add('HTML external hyperlinks require online navigation and are unsupported')
            elif tag=='img' and name=='src':
                parsed=urlsplit(value)
                path=unquote(parsed.path)
                if not parsed.scheme and not parsed.netloc and path.startswith('/api/asset/') and '..' not in path.split('/') and '\\' not in path and not parsed.query and not parsed.fragment:
                    clean[name]=value
                elif re.fullmatch(r'data:image/(?:png|jpeg|gif|webp);base64,[A-Za-z0-9+/=\s]+',value):clean[name]=value
                else:self.issues.add('HTML image source is unsupported; use a local asset or embedded bitmap')
            else:self.issues.add(f'HTML attribute {tag}.{name} is unsupported')
        if tag=='a' and 'data-emu-link' in clean:clean['role']='link'
        self.output.append('<'+tag+''.join(' '+k+'="'+escape(v,quote=True)+'"' for k,v in clean.items())+'>')
        node={'tag':tag,'styles':css,'attrs':clean,'children':[]};self.nodes[-1]['children'].append(node)
        if tag not in VOID:self.stack.append(tag);self.nodes.append(node)
    def handle_startendtag(self,tag,attrs):
        self.handle_starttag(tag,attrs)
        if tag not in VOID:self.handle_endtag(tag)
    def handle_endtag(self,tag):
        if self.dropped:
            if tag in self.dropped:
                del self.dropped[len(self.dropped)-1-self.dropped[::-1].index(tag):]
            return
        if tag not in self.stack:return
        index=len(self.stack)-1-self.stack[::-1].index(tag)
        for name in reversed(self.stack[index:]):self.output.append('</'+name+'>')
        del self.stack[index:];del self.nodes[index+1:]
    def handle_data(self,data):
        if not self.dropped:self.output.append(escape(data));self.nodes[-1]['children'].append(data)
    def finish(self):
        self.close()
        for name in reversed(self.stack):self.output.append('</'+name+'>')
        return {'html':''.join(self.output),'issues':tuple(sorted(self.issues)),'tree':self.root}


@lru_cache(maxsize=128)
def fragment(source):
    parser=Fragment()
    if len(source)>1_000_000:
        parser.issues.add('HTML fragments over one million characters are unsupported');source=source[:1_000_000]
    parser.feed(source);return parser.finish()


def length(value,base,font,default=0):
    m=re.fullmatch(r'(-?\d+(?:\.\d+)?)(px|pt|em|rem|%)?',str(value).strip())
    if not m:return default
    n=float(m[1]);unit=m[2]
    return n*(font if unit=='em' else 14 if unit=='rem' else base/100 if unit=='%' else 4/3 if unit=='pt' else 1)


def estimate(node,width,font=14,line=1.45):
    """Block/inline line-wrapping estimate, bounded by the control's 7680 cap.

    CSS flex/grid, real font glyphs, table column sizing and positioned content
    need browser/Studio comparison; this function never runs formulas in JS.
    """
    css=node['styles'];tag=node['tag']
    if css.get('display')=='none' or css.get('position')=='absolute':return 0
    font=length(css.get('font-size',font),font,font,font)
    if tag.startswith('h') and len(tag)==2 and tag[1].isdigit() and 'font-size' not in css:font*=max(1,2.2-int(tag[1])*.2)
    line_px=font*line
    if 'line-height' in css:
        raw=css['line-height'];line_px=float(raw)*font if re.fullmatch(r'\d+(?:\.\d+)?',raw) else length(raw,font,font,line_px)
    width=max(1,length(css.get('width',width),width,font,width))
    padding=length(css.get('padding','0'),width,font)
    inset=sum(length(css.get('padding-'+side,padding),width,font,padding) for side in ('left','right'))
    available=max(1,width-inset);text='';height=0
    def flush():
        nonlocal text,height
        if text:
            chunks=text.split('\n') if css.get('white-space') in ('pre','pre-wrap') or tag=='pre' else [re.sub(r'\s+',' ',text)]
            chars=max(1,int(available/max(1,font*.55)))
            height+=sum(max(1,math.ceil(len(s)/chars)) for s in chunks)*line_px;text=''
    for child in node['children']:
        if isinstance(child,str):text+=child
        elif child['tag']=='br':
            had_text=bool(text);flush()
            if not had_text:height+=line_px
        elif child['tag'] in BLOCKS or child['styles'].get('display') in ('block','flex'):
            flush();height+=estimate(child,available,font,line)
        elif child['tag']=='img':
            flush();height+=length(child['attrs'].get('height',child['styles'].get('height',font)),width,font,font)
        else:
            # Inline descendants share wrapping; explicit spans keep their text.
            def flatten(n):return ''.join(c if isinstance(c,str) else '\n' if c['tag']=='br' else flatten(c) for c in n['children'])
            text+=flatten(child)
    flush()
    height+=sum(length(css.get('padding-'+side,padding),width,font,padding) for side in ('top','bottom'))
    height=max(height,length(css.get('height',0),height,font))
    height=max(height,length(css.get('min-height',0),height,font))
    margin=length(css.get('margin',0),width,font)
    return height+sum(length(css.get('margin-'+side,margin),width,font,margin) for side in ('top','bottom'))


def auto_height(ref,base):
    html=ref.property('HtmlText') or ''
    width=max(1,ref.property('Width')-ref.property('PaddingLeft')-ref.property('PaddingRight')-2*ref.property('BorderThickness'))
    h=estimate(fragment(html)['tree'],width,ref.property('Size'))+ref.property('PaddingTop')+ref.property('PaddingBottom')+2*ref.property('BorderThickness')
    return min(7680,max(float(base),math.ceil(h)))
