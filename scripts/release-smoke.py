"""Owner-run HTTPS acceptance against the selected built artifact. No secrets logged."""
import hashlib
import http.cookiejar
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request


def client():
    origin=os.environ['SIERX_SMOKE_URL'].rstrip('/')
    parsed=urllib.parse.urlsplit(origin)
    if parsed.scheme!='https' or parsed.username or parsed.path or parsed.query or parsed.fragment:
        raise ValueError('SIERX_SMOKE_URL must be an HTTPS origin')
    jar=http.cookiejar.CookieJar()
    opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    def call(path,body=None):
        headers={'Accept':'application/json','Origin':origin}
        data=None
        if body is not None:
            headers['Content-Type']='application/json'
            data=json.dumps(body).encode()
        with opener.open(urllib.request.Request(origin+path,data=data,headers=headers),timeout=20) as response:
            return response, response.read()
    call('/api/v1/auth/login',{'email':os.environ['SIERX_SMOKE_EMAIL'],'password':os.environ['SIERX_SMOKE_PASSWORD'],'code':os.environ.get('SIERX_SMOKE_CODE','')})
    cookie=next((c for c in jar if c.name=='__Host-sierx_session'),None)
    if cookie is None or not cookie.secure or cookie.path!='/' or not cookie.has_nonstandard_attr('HttpOnly'):
        raise ValueError('Protected HTTPS session cookie is missing')
    return call


def smoke():
    call=client()
    response,data=call('/api/v1/me')
    if response.headers.get('Cache-Control')!='no-store':
        raise ValueError('Account response is cacheable')
    key=os.environ['SIERX_SMOKE_ITEM']
    if not __import__('re').fullmatch(r'[A-Z][A-Z0-9]*-[1-9][0-9]*',key):
        raise ValueError('Set an existing item key')
    _,item=call('/api/v1/items/'+key)
    item=json.loads(item)
    for path in ['/', '/?q='+urllib.parse.quote('project = '+item['project']['key_prefix']), '/'+key]:
        response,html=call(path)
        if b'id="sierx-state"' not in html or 'no-store' not in response.headers.get('Cache-Control',''):
            raise ValueError('Document initial state or private caching is missing')
    fingerprint=hashlib.sha256(json.dumps({k:item[k] for k in ['id','key','title','body','version','change_seq']},sort_keys=True).encode()).hexdigest()
    call('/api/v1/auth/logout',{})
    print('release-smoke: HTTPS login, protected cookie, projected item and deep-link documents passed')
    print('release-smoke: item fingerprint '+fingerprint+' (compare before/after restart)')

if __name__=='__main__':
    try: smoke()
    except (KeyError,ValueError,OSError,urllib.error.URLError):
        sys.exit('release-smoke: failed; check private inputs, certificate trust and application logs')
