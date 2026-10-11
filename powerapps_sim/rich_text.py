"""Rich text editor contracts and authoritative HTML values.

Template properties/defaults were recovered from Microsoft's shipped 2.3.0
AccountPlanReviewerMaster app; 2.5.0/2.6.0 are present in Microsoft Teams apps.
Exact toolbar markup and change timing still require Studio comparison.
"""
from functools import lru_cache
from html import escape
import re,math
from decimal import Decimal
from urllib.parse import urlsplit
from .html_controls import Fragment,validate as html_validate
from .html_fx import plain_text
from .syntax import FxError

VERSIONS={'2.3.0','2.5.0','2.6.0'}
DEFAULTS={'Default':'=""','EnableSpellCheck':'=true','Reset':'=false','TabIndex':'=0',
          'Width':'=515','Height':'=158','BorderColor':'=RGBA(166,166,166,1)'}
TYPES={'Default':'Text','HtmlText':'Text','EnableSpellCheck':'Boolean','Reset':'Boolean','TabIndex':'Number',
       **{p:'Number' for p in ('X','Y','Width','Height','Size')},'BorderColor':'Color'}
COMMANDS=frozenset(('bold','italic','underline','foreColor','hiliteColor','fontSize',
                   'insertOrderedList','insertUnorderedList','createLink','unlink','removeFormat','undo','redo','insertHTML'))


class EditorFragment(Fragment):
    def handle_starttag(self,tag,attrs):
        href=None
        if tag=='font':
            tag='span';css=[];keep=[]
            for name,value in attrs:
                if name=='color':css.append('color:'+str(value))
                elif name=='face':css.append('font-family:'+str(value))
                elif name=='size':
                    sizes={'1':10,'2':13,'3':16,'4':18,'5':24,'6':32,'7':48}
                    if value in sizes:css.append(f'font-size:{sizes[value]}px')
                    else:self.issues.add('Rich text font size is unsupported')
                elif name=='style':css.append(value or '')
                else:keep.append((name,value))
            attrs=keep+[('style',';'.join(css))]
        if tag=='a':
            keep=[]
            for name,value in attrs:
                if name=='href':
                    value=value or ''
                    try:scheme=urlsplit(value).scheme.lower()
                    except ValueError:scheme='invalid'
                    if scheme not in ('','http','https','mailto','tel') or re.search(r'[\x00-\x20\x7f\\]',value):
                        self.issues.add('Rich text hyperlink scheme or characters are unsupported')
                    else:href=value
                else:keep.append((name,value))
            attrs=keep
        old_count=len(self.output)
        super().handle_starttag(tag,attrs)
        if href is not None and len(self.output)>old_count and self.stack and self.stack[-1]=='a':
            self.output[-1]=self.output[-1][:-1]+' href="'+escape(href,quote=True)+'">'
            self.nodes[-1]['attrs']['href']=href
    def handle_endtag(self,tag):super().handle_endtag('span' if tag=='font' else tag)


def sanitize(source):
    if not isinstance(source,str):raise ValueError('Rich text requires an HTML string')
    if len(source)>1_000_000:raise ValueError('Rich text exceeds the one million character simulator limit')
    return _sanitize(source)


@lru_cache(maxsize=128)
def _sanitize(source):
    parser=EditorFragment();parser.feed(source);result=parser.finish()
    html=result['html']
    # Empty editor paragraphs must validate like an empty multiline card.
    if not plain_text(html) and not re.search(r'<img\b[^>]*\bsrc=',html):html=''
    return {'html':html,'issues':result['issues']}


def validate(name,value):
    if name in ('EnableSpellCheck','Reset'):
        if not isinstance(value,bool):raise FxError(f'RichTextEditor.{name} requires a Boolean','Type')
    elif name=='TabIndex':
        if isinstance(value,bool) or not isinstance(value,(int,float,Decimal)) or not math.isfinite(float(value)):raise FxError('RichTextEditor.TabIndex requires a finite Number','Type')
        if value!=int(value):raise FxError('RichTextEditor.TabIndex requires an integer','Type')
    elif name in ('Width','Height','Size','X','Y'):html_validate(name,value)


def clean_value(ref,source):
    if source is None:source=''
    try:result=sanitize(source)
    except ValueError as error:raise FxError(str(error),'Validation') from None
    return result['html']


def issues(runtime,ref,messages):
    for message in messages:
        runtime.diagnostic(FxError(message,'Unsupported'),ref.control.source,ref.name+'.HtmlText',ref.raw_property('Default'))


def event(runtime,ref,name,value):
    if name=='OnEditorIssue':
        if not isinstance(value,dict) or set(value)!={'command'} or not isinstance(value['command'],str) or value['command'] not in COMMANDS:raise ValueError('Invalid editor command diagnostic')
        runtime.diagnostic(FxError(f'Rich text command {value["command"]} is unsupported by this browser','Unsupported'),ref.control.source,ref.name+'.Formatting')
        return
    if name!='OnChange':raise ValueError('Rich text editor only accepts value changes')
    ref.sync_default('HtmlText')
    if isinstance(value,dict):
        if set(value)!={'html','reset_token'} or not isinstance(value['reset_token'],str):raise ValueError('Invalid rich text input event')
        if value['reset_token']!=runtime.text_token(ref):return
        value=value['html']
    result=sanitize(value)
    previous=ref.property('HtmlText');baseline=clean_value(ref,runtime.input_baselines.get(ref.path))
    ref.state.update(HtmlText=result['html'],dirty=result['html']!=baseline,rich_issues=result['issues'])
    runtime.invalidate();issues(runtime,ref,result['issues'])
    if result['html']!=previous:runtime.run_event(ref,'OnChange')
    runtime.drain_events()
