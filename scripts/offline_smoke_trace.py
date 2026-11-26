"""Failure-only fixed metadata from an unchanged historical HTTPS smoke script."""
import http.client,json,os,re,ssl,sys,urllib.error

MARKER='SIERX_SMOKE_FAILURE: '
STEPS={'login','account','item','home-document','query-document','item-document','logout','unknown'}
KINDS={'HTTPError','URLError','SSLCertVerificationError','SSLError','TimeoutError',
    'ConnectionRefusedError','ConnectionResetError','RemoteDisconnected','HTTPException',
    'OSError','ValueError','KeyError','JSONDecodeError','UnicodeDecodeError','IncompleteRead'}
TRANSPORTS={'timeout','certificate','tls','connection','http-protocol','transport','other'}


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
    for field,low,high in (('errno',1,4095),('http_status',100,599)):
        number=record.get(field)
        if type(number) is int and low<=number<=high:value[field]=number
    return value


def summarize(error,traceback,source,step):
    lines=[]
    while traceback is not None:
        if traceback.tb_frame.f_code.co_filename==source:lines.append(traceback.tb_lineno)
        traceback=traceback.tb_next
    value={'step':step,'kind':type(error).__name__,'lines':lines[-8:]}
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
    failure=None;step='unknown'
    def on_event(frame,event,args):
        nonlocal failure,step
        if event=='call' and frame.f_code.co_name=='call':step=request_step(frame.f_locals.get('path'))
        if event=='exception':
            kind,error,traceback=args
            if kind is SystemExit:
                if error.code not in (None,0) and failure is not None:
                    try:os.write(2,(MARKER+json.dumps(failure,separators=(',',':'))+'\n').encode('ascii'))
                    except OSError:pass
            else:
                value=summarize(error,traceback,source,step)
                if value is not None:failure=value
        return on_event
    def trace(frame,event,_args):
        if frame.f_code.co_filename==source:
            frame.f_trace_lines=False
            return on_event(frame,event,_args)
        return None
    sys.settrace(trace)
