"""Pinned built-in enum identity and conversions, isolated from Canvas controls."""
from dataclasses import dataclass
from decimal import Decimal
from .errors import ERROR_KINDS
from .syntax import FxError

from .regex_constants import MATCH_MEMBERS, MATCH_OPTIONS

ENUM_MODES={'legacy','strong'}
CATALOG={
 'LinkAppearance':{'kind':'Text','to_backing':False,'from_backing':False,'compare':False,'members':{'Default':'Default','Subtle':'Subtle'}},
 'DataSourceInfo':{'kind':'Text','to_backing':False,'from_backing':False,'compare':False,'members':{n:n for n in ('MaxLength','DisplayName','Required','MinValue','MaxValue','EditPermission','CreatePermission','DeletePermission','ReadPermission','AllowedValues')}},
 'RatingStep':{'kind':'Text','to_backing':False,'from_backing':False,'compare':False,'members':{'Full':'Full','Half':'Half'}},
 'Match':{'kind':'Text','to_backing':False,'from_backing':True,'compare':False,'concatenate':True,'members':MATCH_MEMBERS},
 'MatchOptions':{'kind':'Text','to_backing':False,'from_backing':False,'compare':False,'concatenate':True,'members':MATCH_OPTIONS},
 'JSONFormat':{'kind':'Text','to_backing':False,'from_backing':False,'compare':False,'concatenate':True,'members':{'Compact':'','IndentFour':'4','IncludeBinaryData':'B','IgnoreBinaryData':'G','IgnoreUnsupportedTypes':'I','FlattenValueTables':'_'}},
 'ErrorKind':{'kind':'Number','to_backing':True,'from_backing':False,'compare':True,'members':ERROR_KINDS},
 'StartOfWeek':{'kind':'Number','to_backing':False,'from_backing':False,'compare':False,'members':{'Sunday':1,'Monday':2,'MondayZero':3,'Tuesday':12,'Wednesday':13,'Thursday':14,'Friday':15,'Saturday':16}},
 'TimeUnit':{'kind':'Text','to_backing':False,'from_backing':False,'compare':False,'members':{n:n.lower() for n in ('Years','Quarters','Months','Days','Hours','Minutes','Seconds','Milliseconds')}},
 'SortOrder':{'kind':'Text','to_backing':False,'from_backing':False,'compare':False,'members':{'Ascending':'ascending','Descending':'descending'}},
 'DateTimeFormat':{'kind':'Text','to_backing':False,'from_backing':True,'compare':False,'members':{n:("'"+n.lower()+"'" if n!='UTC' else 'utc') for n in ('LongDate','ShortDate','LongTime','ShortTime','LongTime24','ShortTime24','LongDateTime','ShortDateTime','LongDateTime24','ShortDateTime24','UTC')}}
}

@dataclass(frozen=True)
class EnumValue:
 namespace:str
 member:str
 backing:object
 @property
 def spec(self):return CATALOG[self.namespace]
 def text(self):return str(self.backing) if self.spec['kind']=='Text' else self.member
 def json(self):return {'$enum':{'namespace':self.namespace,'member':self.member,'value':self.backing}}

from .status_enums import BADGE_ENUMS
CATALOG.update({ns:{'kind':'Text','to_backing':False,'from_backing':False,'compare':False,'members':{member:member for member in members}} for ns,members in BADGE_ENUMS.items()})

VALUES={ns:{member:EnumValue(ns,member,value) for member,value in spec['members'].items()} for ns,spec in CATALOG.items()}

def numeric(value,explicit=False):
 if not isinstance(value,EnumValue):return value
 if value.spec['kind']!='Number' or not (explicit or value.spec['to_backing']):
  raise FxError(f'{value.namespace} cannot convert to a number','Type')
 return value.backing

def consume(value,namespace):
 if isinstance(value,EnumValue):
  if value.namespace!=namespace:raise FxError(f'Expected {namespace}, received {value.namespace}','Type')
  return value.member
 return value

def comparison(a,b,ordered=False):
 enum=a if isinstance(a,EnumValue) else b if isinstance(b,EnumValue) else None
 if enum is None:return a,b
 other=b if enum is a else a
 if isinstance(other,EnumValue):
  if enum.namespace!=other.namespace:raise FxError('Cannot compare different enum types','Type')
 elif other is not None and (not (enum.spec['to_backing'] or enum.spec['from_backing']) or enum.spec['kind']=='Number' and (isinstance(other,bool) or not isinstance(other,(int,float,Decimal))) or enum.spec['kind']=='Text' and not isinstance(other,str)):
  raise FxError(f'{enum.namespace} cannot compare with its backing type','Type')
 if ordered and not enum.spec['compare']:raise FxError(f'{enum.namespace} does not support ordered comparison','Type')
 return (a.backing if isinstance(a,EnumValue) else a,b.backing if isinstance(b,EnumValue) else b)


def concatenate_namespace(types):
 meaningful=[typ for typ in types if typ and typ.kind not in ('Blank','Error')]
 enums=[typ for typ in meaningful if typ.kind=='Enum']
 if not enums:return None
 namespace=enums[0].name;spec=CATALOG[namespace]
 if not spec.get('concatenate'):return None
 if all(typ.kind=='Enum' and typ.name==namespace for typ in meaningful):return namespace
 if spec.get('from_backing') and all(typ.kind!='Enum' or typ.name==namespace for typ in meaningful):return namespace
 return None

def namespace_values(namespace,environment,legacy_values=None):
 if namespace=='Match':
  from .regex_fx import members
  values=members(environment)
 elif namespace=='MatchOptions':values=MATCH_OPTIONS
 else:return VALUES[namespace] if environment.get('enum_mode')=='strong' and namespace in VALUES else legacy_values
 return {key:EnumValue(namespace,key,value) for key,value in values.items()} if environment.get('enum_mode')=='strong' else values

def concatenated(namespace,backing):
 return EnumValue(namespace,'CalculatedOptionSetValue',backing) if namespace else backing
