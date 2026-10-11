"""Deferred Canvas App.OnError observation, separate from pure evaluation."""
from collections import deque
from copy import deepcopy
import json
from .syntax import FxError


def scope_records(error,observed=''):
    rows=error.located('',observed or None).records()
    return [{**row,'Details':row.get('Details')} for row in rows]


def scope_type():
    from .binding import record,tabular,TEXT,NUMBER
    row=record({'Kind':NUMBER,'Message':TEXT,'Source':TEXT,'Observed':TEXT,
                'Details':record({'HttpStatusCode':NUMBER,'HttpResponse':TEXT},open=True)})
    return {'FirstError':row,'AllErrors':tabular(row)}


class AppErrors:
    def __init__(self,runtime):
        self.runtime=runtime;self.reset()

    def reset(self):
        self.pending=deque();self.property_errors={};self.reports=[];self.sequence=0
        self.handling=False;self.banner=None

    def observe(self,error,observed,source='',member='',formula=None,*,property=False):
        error=error.located(observed,observed)
        rows=scope_records(error,observed)
        if property:
            from .runtime import serial
            signature=json.dumps(serial(rows),sort_keys=True)
            if self.property_errors.get(observed)==signature:return
            self.property_errors[observed]=signature
        if self.handling:
            # Errors in OnError itself cannot recursively invoke the handler.
            self.runtime.diagnostic(error,source,member,formula)
            self.default_banner(error);return
        self.pending.append((error,observed,source,member,formula))

    def healthy(self,observed):
        self.property_errors.pop(observed,None)

    def default_banner(self,error):
        message=error.record()['Message']
        if self.banner!=message:
            self.runtime.notifications.append({'message':message,'tone':'Error','origin':'App.OnError'})
            self.banner=message

    def drain(self):
        if self.handling or not self.pending:return False
        runtime=self.runtime;self.handling=True;count=0;changed=False
        try:
            while self.pending and count<100:
                error,observed,source,member,formula=self.pending.popleft();count+=1
                self.sequence+=1;rows=scope_records(error,observed)
                entry={'sequence':self.sequence,'observed':observed,'records':deepcopy(rows),'handled':False}
                self.reports.append(entry);self.reports=self.reports[-100:]
                from .runtime import serial
                runtime.trace_event('app-error',observed=observed,records=serial(rows))
                raw=runtime.project.app.get('OnError')
                if raw:
                    from .fx import Context
                    ctx=Context(runtime,behavior=True,error_source='App.OnError').scope({'FirstError':rows[0],'AllErrors':rows})
                    result=runtime.execute(raw,ctx,runtime.app_source(),'App.OnError',observe_errors=False)
                    changed=True
                    if isinstance(result,FxError):
                        runtime.diagnostic(result,runtime.app_source(),'App.OnError',raw)
                        self.default_banner(result)
                    else:entry['handled']=True
                else:self.default_banner(error)
            if self.pending:
                self.pending.clear();runtime.diagnostic(FxError('App.OnError observation loop exceeded 100 reports','Cycle'),runtime.app_source(),'App.OnError')
        finally:self.handling=False
        return changed
