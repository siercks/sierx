"""Failure-only fixed metadata from an unchanged historical HTTPS smoke script."""
import http.client,json,os,re,ssl,sys,time,urllib.error
from pathlib import Path

MARKER='SIERX_SMOKE_FAILURE: '
STEPS={'login','account','item','home-document','query-document','item-document','logout','unknown'}
KINDS={'HTTPError','URLError','SSLCertVerificationError','SSLError','TimeoutError',
    'ConnectionRefusedError','ConnectionResetError','RemoteDisconnected','HTTPException',
    'OSError','ValueError','KeyError','JSONDecodeError','UnicodeDecodeError','IncompleteRead'}
TRANSPORTS={'timeout','certificate','tls','connection','http-protocol','transport','other'}
IO_STAGES={'dns','tcp-connect','tls-handshake','request-send','response-headers','response-body','http-status','unknown'}
PROCESS_ROLES={'sierx':'app','caddy':'gateway','postgres':'database'}


def activity_snapshot(root=Path('/proc')):
    """Private name-matched counters only; no argv, environment or process data."""
    try:
        entries=[entry for entry in root.iterdir() if entry.name.isascii() and entry.name.isdecimal()]
        if len(entries)>4096:return {'capture':'limit-exceeded'}
        tasks={};raced=0
        for entry in entries:
            try:
                with (entry/'stat').open() as stream:row=stream.read(4097)
            except (FileNotFoundError,ProcessLookupError):
                raced+=1;continue
            if len(row)>4096:raise ValueError('Process stat exceeds bound')
            prefix,separator,tail=row.rpartition(') ')
            pid,opening,comm=prefix.partition(' (')
            if not separator or not opening or pid!=entry.name:raise ValueError('Invalid process stat')
            role=PROCESS_ROLES.get(comm)
            if role is None:continue
            fields=tail.split()
            if len(fields)<20:raise ValueError('Incomplete process stat')
            ticks=int(fields[11])+int(fields[12]);started=int(fields[19])
            if ticks<0 or started<0:raise ValueError('Negative process counter')
            tasks[(role,int(pid),started)]=ticks
        hz=os.sysconf('SC_CLK_TCK')
        if not 1<=hz<=100000:raise ValueError('Unknown counter frequency')
        return {'capture':'observed','tasks':tasks,'hz':hz,'raced':raced,'time_ns':time.monotonic_ns()}
    except (OSError,ValueError,AttributeError):return {'capture':'unavailable'}


def sanitize_activity(value):
    if not isinstance(value,dict):return None
    capture=value.get('capture')
    if capture in ('unavailable','limit-exceeded','inconsistent'):return {'capture':capture}
    if capture!='observed':return None
    fields={'elapsed_ms':600000,'raced_entries':8192}
    if any(type(value.get(key)) is not int or not 0<=value[key]<=maximum for key,maximum in fields.items()):return None
    safe={'capture':'observed','scope':'name-matched-guest-processes',**{key:value[key] for key in fields}}
    roles=value.get('roles')
    if not isinstance(roles,dict) or set(roles)!=set(PROCESS_ROLES.values()):return None
    safe['roles']={}
    for role in PROCESS_ROLES.values():
        counters=roles[role]
        if not isinstance(counters,dict):return None
        limits={'start_tasks':4096,'end_tasks':4096,'matched_tasks':4096,'gone_tasks':4096,'new_tasks':4096,'cpu_ms':2147483647}
        if any(type(counters.get(key)) is not int or not 0<=counters[key]<=maximum for key,maximum in limits.items()):return None
        if (counters['matched_tasks']+counters['gone_tasks']!=counters['start_tasks']
                or counters['matched_tasks']+counters['new_tasks']!=counters['end_tasks']):return None
        safe['roles'][role]={key:counters[key] for key in limits}
    return safe


def activity_summary(before,after):
    """CPU deltas include only identical role/PID/start-time identities."""
    if before.get('capture')!='observed' or after.get('capture')!='observed':
        return {'capture':'limit-exceeded' if 'limit-exceeded' in (before.get('capture'),after.get('capture')) else 'unavailable'}
    if before['hz']!=after['hz'] or after['time_ns']<before['time_ns']:return {'capture':'inconsistent'}
    roles={}
    for role in PROCESS_ROLES.values():
        first={key:count for key,count in before['tasks'].items() if key[0]==role}
        last={key:count for key,count in after['tasks'].items() if key[0]==role}
        common=first.keys()&last.keys()
        if any(last[key]<first[key] for key in common):return {'capture':'inconsistent'}
        roles[role]={'start_tasks':len(first),'end_tasks':len(last),'matched_tasks':len(common),
            'gone_tasks':len(first.keys()-last.keys()),'new_tasks':len(last.keys()-first.keys()),
            'cpu_ms':sum(last[key]-first[key] for key in common)*1000//before['hz']}
    return sanitize_activity({'capture':'observed','elapsed_ms':(after['time_ns']-before['time_ns'])//1000000,
        'raced_entries':before['raced']+after['raced'],'roles':roles}) or {'capture':'inconsistent'}


def request_step(path):
    if not isinstance(path,str):return 'unknown'
    fixed={'/api/v1/auth/login':'login','/api/v1/me':'account','/':'home-document','/api/v1/auth/logout':'logout'}
    if path in fixed:return fixed[path]
    if re.fullmatch(r'/api/v1/items/[A-Z][A-Z0-9]*-[1-9][0-9]*',path):return 'item'
    if re.fullmatch(r'/[A-Z][A-Z0-9]*-[1-9][0-9]*',path):return 'item-document'
    return 'query-document' if path.startswith('/?q=') else 'unknown'


def sanitize(record):
    if (not isinstance(record,dict) or not isinstance(record.get('step'),str) or record['step'] not in STEPS
            or not isinstance(record.get('kind'),str) or record['kind'] not in KINDS):return None
    lines=record.get('lines')
    if not isinstance(lines,list) or not 1<=len(lines)<=8 or any(type(n) is not int or not 1<=n<=100000 for n in lines):return None
    value={key:record[key] for key in ('step','kind','lines')}
    transport=record.get('transport')
    if isinstance(transport,str) and transport in TRANSPORTS:value['transport']=transport
    io=record.get('io_stage')
    if isinstance(io,str) and io in IO_STAGES:value['io_stage']=io
    activity=sanitize_activity(record.get('activity'))
    if activity is not None:value['activity']=activity
    for field,low,high in (('errno',1,4095),('http_status',100,599)):
        number=record.get(field)
        if type(number) is int and low<=number<=high:value[field]=number
    return value


def io_stage(error,traceback):
    if isinstance(error,urllib.error.HTTPError):return 'http-status'
    locations=set()
    reason=getattr(error,'reason',None)
    traces=[traceback]
    if isinstance(reason,BaseException):traces.append(reason.__traceback__)
    for entry in traces:
        while entry is not None:
            frame=entry.tb_frame;module=frame.f_globals.get('__name__')
            if isinstance(module,str) and module in {'socket','ssl','http.client','urllib.request'}:
                locations.add((module,frame.f_code.co_name))
            entry=entry.tb_next
    # Classify only public standard-library function boundaries. Never inspect
    # socket data, request headers/URLs, exception text or private frame locals.
    if ('socket','getaddrinfo') in locations:return 'dns'
    if ('ssl','do_handshake') in locations:return 'tls-handshake'
    if any(('http.client',name) in locations for name in ('getresponse','begin','_read_status')):return 'response-headers'
    if any(('http.client',name) in locations for name in ('read','readinto','_safe_read')):return 'response-body'
    if ('socket','create_connection') in locations or ('http.client','connect') in locations:return 'tcp-connect'
    if any(('http.client',name) in locations for name in ('send','_send_output','_send_request')):return 'request-send'
    return 'unknown'


def summarize(error,traceback,source,step):
    io=io_stage(error,traceback)
    lines=[]
    while traceback is not None:
        if traceback.tb_frame.f_code.co_filename==source:lines.append(traceback.tb_lineno)
        traceback=traceback.tb_next
    value={'step':step,'kind':type(error).__name__,'lines':lines[-8:],'io_stage':io}
    reason=getattr(error,'reason',error)
    kinds=((TimeoutError,'timeout'),(ssl.SSLCertVerificationError,'certificate'),(ssl.SSLError,'tls'),
        (ConnectionError,'connection'),(http.client.HTTPException,'http-protocol'),(OSError,'transport'))
    value['transport']=next((label for kind,label in kinds if isinstance(reason,kind)),'other')
    value['errno']=getattr(error,'errno',None) or getattr(reason,'errno',None)
    if isinstance(error,urllib.error.HTTPError):value['http_status']=error.code
    return sanitize(value)


def stderr_failure(stderr):
    if not isinstance(stderr,bytes) or len(stderr)>8192:return None
    prefix=MARKER.encode('ascii')
    rows=[line[len(prefix):] for line in stderr.splitlines() if line.startswith(prefix)]
    if len(rows)!=1 or len(rows[0])>1024:return None
    try:return sanitize(json.loads(rows[0]))
    except (ValueError,UnicodeError):return None


def install():
    source=os.environ.get('SIERX_DIAGNOSTIC_SMOKE')
    if not source or sys.argv[1:] or os.path.abspath(sys.argv[0])!=source:return
    failure=None;step='unknown';activity=None;finished_activity=None
    def on_event(frame,event,args):
        nonlocal failure,step,activity,finished_activity
        if event=='call' and frame.f_code.co_name=='call':
            step=request_step(frame.f_locals.get('path'))
            activity=activity_snapshot();finished_activity=None
        if event=='exception':
            kind,error,traceback=args
            if kind is SystemExit:
                if error.code not in (None,0) and failure is not None:
                    try:os.write(2,(MARKER+json.dumps(failure,separators=(',',':'))+'\n').encode('ascii'))
                    except OSError:pass
            else:
                value=summarize(error,traceback,source,step)
                if value is not None:
                    if activity is not None:
                        if finished_activity is None:finished_activity=activity_summary(activity,activity_snapshot())
                        value['activity']=finished_activity
                    failure=value
        return on_event
    def trace(frame,event,_args):
        if frame.f_code.co_filename==source:
            frame.f_trace_lines=False
            return on_event(frame,event,_args)
        return None
    sys.settrace(trace)
