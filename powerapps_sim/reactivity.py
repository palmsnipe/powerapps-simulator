"""Retain volatile data-flow results while their observed inputs are unchanged.

Ordinary rules keep the runtime's existing caches. Only rules that execute a
volatile operation (or read another volatile rule) survive broad invalidation.
Dependency probes read values; they never execute behavior rules.
"""
from dataclasses import dataclass, field
from contextlib import contextmanager
import hashlib
import json
import random

from .syntax import FxError


def fingerprint(value):
    from .runtime import serial
    from .store import DataSource
    if isinstance(value, DataSource):
        value = {'source':value.name, 'schema':value.store.definitions[value.name]}
    from .json_fx import Media
    def identity(v):
        if isinstance(v, Media):
            return {'$mediaIdentity': [v.media_kind, str(v), str(v.asset_root) if v.asset_root else None]}
        if isinstance(v, dict):
            return {k: identity(item) for k, item in v.items()}
        if isinstance(v, list):
            return [identity(item) for item in v]
        return serial(v)
    payload = identity(value)
    return json.dumps(payload, sort_keys=True, ensure_ascii=True, default=repr)


def outcome(loader):
    try:
        return loader()
    except FxError as error:
        return error


def unwrap(value):
    if isinstance(value, FxError):
        raise value
    return value


@dataclass
class Frame:
    key: tuple
    dependencies: dict = field(default_factory=dict)
    volatile: bool = False


@dataclass
class Entry:
    value: object
    signature: object
    dependencies: list
    epoch: int


class ReactiveValues:
    def __init__(self, runtime):
        self.runtime = runtime
        self.epoch = 0
        self.entries = {}
        self.frames = []
        self.checking = set()
        self.streams = {}
        self.observations = {}
        self.metadata = {}
        self.seed = runtime.environment.get('random_seed')

    def invalidate(self):
        self.epoch += 1

    def reset(self):
        self.entries.clear()
        self.streams.clear()
        self.observations.clear()
        self.metadata.clear()
        self.seed = self.runtime.environment.get('random_seed')
        self.invalidate()

    def profile(self):
        env = self.runtime.environment
        return tuple(env.get(k) for k in ('number_mode','language','enum_mode',
                    'date_numeric_mode','round_table_mode','regex_mode','random_seed'))

    def record(self, key, loader, value, volatile=False):
        if self.frames:
            frame = self.frames[-1]
            frame.dependencies[key] = (loader, value)
            frame.volatile |= volatile

    @contextmanager
    def untracked(self):
        saved,self.frames=self.frames,[]
        try:yield
        finally:self.frames=saved

    def leaf(self, key, loader, isolated=False):
        if isolated:
            with self.untracked():value=outcome(loader)
        else:value = outcome(loader)
        self.record(key, loader, value)
        return unwrap(value)

    def project(self,key,loader):
        """Observe a member result without retaining its intermediate records.

        The isolated frame preserves volatility inherited from property rules.
        Probes still evaluate only pure member access; whole-record consumers
        continue to use the ordinary leaves/rules.
        """
        saved=self.frames
        frame=Frame(key)
        self.frames=[frame]
        try:value=outcome(loader)
        finally:self.frames=saved
        self.record(key,lambda:self.project(key,loader),value,frame.volatile)
        return unwrap(value)

    def unit(self, key, loader, signature=lambda:None, forget=lambda:None):
        # Re-entrant layout reads must reach the existing intrinsic-size/cycle
        # handling, rather than treating the special layout fallback as a rule.
        if any(frame.key == key for frame in self.frames):
            return loader()
        entry = self.entries.get(key)
        reason='First evaluation';changed=None
        if entry is not None:
            current_signature = (self.profile(), signature())
            valid = entry.signature == current_signature
            if not valid:reason='Host profile changed' if entry.signature[0]!=current_signature[0] else 'Source changed'
            if valid and entry.epoch != self.epoch:
                if key in self.checking:
                    raise FxError('Volatile formula dependency cycle', 'Cycle')
                self.checking.add(key)
                # Probing dependencies must not become dependencies of the
                # caller. Its single dependency is this rule's returned value.
                saved_frames, self.frames = self.frames, []
                try:
                    for dep_key,probe,expected in entry.dependencies:
                        if fingerprint(outcome(probe))!=expected:
                            valid=False;reason='Input changed';changed=dep_key
                            break
                finally:
                    self.frames = saved_frames
                    self.checking.discard(key)
            if valid:
                entry.epoch = self.epoch
                self.observations[key]['reuses']+=1
                self.observations[key]['checked_epoch']=self.epoch
                self.record(key, lambda:self.unit(key,loader,signature,forget), entry.value, True)
                return unwrap(entry.value)
            self.entries.pop(key, None)
            forget()
        frame = Frame(key)
        self.frames.append(frame)
        try:
            value = outcome(loader)
        finally:
            self.frames.pop()
        if frame.volatile:
            self.entries[key] = Entry(value, (self.profile(),signature()),
                [(dep_key,probe,fingerprint(result)) for dep_key,(probe,result) in frame.dependencies.items()], self.epoch)
            previous=self.observations.get(key,{})
            self.observations[key]={'evaluations':previous.get('evaluations',0)+1,'reuses':previous.get('reuses',0),
                'reason':reason,'changed_input':changed,'evaluated_epoch':self.epoch,'checked_epoch':self.epoch}
        else:self.observations.pop(key,None)
        self.record(key, lambda:self.unit(key,loader,signature,forget), value, frame.volatile)
        return unwrap(value)

    def volatile(self):
        if self.frames:
            self.frames[-1].volatile = True

    def rng(self):
        self.volatile()
        seed = self.runtime.environment.get('random_seed')
        if seed != self.seed:
            self.streams.clear()
            self.seed = seed
        key = self.frames[-1].key if self.frames else ('behavior',)
        if key not in self.streams:
            stream_seed = None if seed is None else int.from_bytes(
                hashlib.sha256(repr((seed,key)).encode()).digest(), 'big')
            self.streams[key] = random.Random(stream_seed)
        return self.streams[key]

    def describe(self,query='',offset=0,limit=100,include_values=True):
        """Snapshot already evaluated rules. Never probe dependencies or draw."""
        from .runtime import serial
        rows=[]
        for key,entry in self.entries.items():
            kind=key[0];path=key[1] if len(key)>1 else '';name=key[2] if len(key)>2 else path
            formula=None;source=None;ref=None
            if kind=='named':
                definition=self.runtime.fx.definitions.get(path)
                if definition:formula=self.runtime.fx.definition_source[definition.body.start:definition.body.end]
                source=self.runtime.app_source();name=path;path='App.Formulas'
            elif kind=='app':
                formula=self.runtime.project.app.get(path);source=self.runtime.app_source();name=path;path='App'
            else:
                ref=self.runtime.refs.get(path)
                if ref:formula=ref.raw_property(name);source=ref.control.source
            metadata=self.metadata.get(key,{})
            if metadata:formula=metadata['formula'];source=metadata['source']
            row={'key':list(key),'kind':kind,'path':path,'name':name,'row_key':key[3] if kind=='row' else None,
                'formula':str(formula) if formula is not None else None,'source':source,
                'dependencies':[list(dep_key) for dep_key,_,_ in entry.dependencies],
                **self.observations[key],**metadata}
            if query.lower() not in (' '.join([kind,path,str(name),str(formula)])).lower():continue
            if include_values:
                value=entry.value
                if kind=='row' and ref and ref.family=='ModernDataGridColumn' and isinstance(value,tuple):
                    value=value[0]
                elif isinstance(value,tuple):value=list(value)
                row['value']=serial(value)
            rows.append(row)
        rows.sort(key=lambda row:(row['path'],row['name'],row['kind'],row['row_key'] or ''))
        return {'epoch':self.epoch,'coverage':'Evaluated volatile rules and their consumers',
            'rows':rows[offset:offset+limit],'total':len(rows),'offset':offset,
            'next_offset':offset+limit if offset+limit<len(rows) else None}


def validate_seed(value):
    if value is not None and (type(value) is not int or abs(value)>9007199254740991):
        raise ValueError('Random seed must be null or a whole number between -9007199254740991 and 9007199254740991')


class ControlState(dict):
    """Observe actual state keys, without depending on every input on a control."""
    def __init__(self,runtime,path,values=()):
        super().__init__(values)
        self.runtime,self.path=runtime,path

    def _current(self):return self.runtime.control_state.get(self.path,{})

    def __contains__(self,key):
        return self.runtime.reactive.leaf(('state-present',self.path,key),
            lambda:dict.__contains__(self._current(),key))

    def get(self,key,default=None):
        return self.runtime.reactive.leaf(('state',self.path,key,fingerprint(default)),
            lambda:dict.get(self._current(),key,default))

    def __getitem__(self,key):
        if key not in self:raise KeyError(key)
        return self.get(key)

    def setdefault(self,key,default=None):
        dict.setdefault(self,key,default)
        return self.get(key)

    def copy(self):return dict(self)

    def __deepcopy__(self,memo):
        from copy import deepcopy
        return deepcopy(dict(self),memo)
