"""Measure fresh Sierx process startup and warmed RSS on an explicit 10k fixture."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.request

spec=importlib.util.spec_from_file_location('bench_http',Path(__file__).with_name('bench-http.py'))
bench=importlib.util.module_from_spec(spec);spec.loader.exec_module(bench)
RSS_LIMIT=80*1024*1024
COLD_LIMIT_MS=1000

def rss_bytes(pid):
    try:
        with open(f'/proc/{pid}/status',encoding='ascii') as stream:
            for line in stream:
                if line.startswith('VmRSS:'):
                    parts=line.split()
                    if len(parts)==3 and parts[2]=='kB':return int(parts[1])*1024
    except (OSError,ValueError):pass
    raise ValueError('process RSS is unavailable; the measurement cannot be skipped')

def port():
    with socket.socket() as listener:
        listener.bind(('127.0.0.1',0));return listener.getsockname()[1]

def stop(process):
    if process is None:return
    if process.poll() is None:
        process.terminate()
        try:process.wait(timeout=5)
        except subprocess.TimeoutExpired:process.kill();process.wait()

def start(binary,timeout=10):
    chosen=port();base=f'http://localhost:{chosen}'
    # The measurement process gets only application inputs; no operator DSN,
    # journal encryption key, backup credentials or private benchmark password.
    allowed=('SIERX_RUNTIME_DATABASE_URL','SIERX_AUTH_DATABASE_URL','SIERX_AUTH_MODE','SIERX_SESSION_KEY',
             'SIERX_LIFECYCLE_CHECKPOINT','SIERX_LIFECYCLE_GUARD_KEY_FILE','SIERX_TRUSTED_PROXIES')
    env={key:os.environ[key] for key in allowed if key in os.environ}
    env.update(SIERX_BASE_URL=base,SIERX_LISTEN_ADDR=f'127.0.0.1:{chosen}')
    began=time.perf_counter_ns()
    process=subprocess.Popen([str(binary)],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            if process.poll() is not None:raise ValueError('measurement process exited before readiness; check protected app configuration')
            try:
                with urllib.request.urlopen(base+'/api/v1/healthz',timeout=.1) as response:
                    health=json.load(response)
                    if response.status==200 and health.get('database')=='reachable':
                        return process,base,(time.perf_counter_ns()-began)/1e6
            except (OSError,ValueError):pass
            time.sleep(.005)
        raise ValueError('fresh measurement process did not become ready')
    except BaseException:stop(process);raise

CONDITION_SECONDS=10

def condition(client,scenarios,observe,seconds=CONDITION_SECONDS):
    # Fixed duration independent of the RSS budget: never wait for a passing value.
    began=time.monotonic();samples=[]
    while time.monotonic()-began<seconds or not samples:
        for paths in scenarios.values():
            for path in paths:client.get(path)
            samples.append(observe())
    return {'fixed_seconds':seconds,'elapsed_seconds':round(time.monotonic()-began,3),
            'rss_samples':len(samples),'rss_max_bytes':max(samples)}

def run(args):
    if sys.platform!='linux':raise ValueError('process acceptance requires Linux /proc RSS data')
    binary=Path(args.binary).resolve()
    if not binary.is_file() or not os.access(binary,os.X_OK):raise ValueError('an accepted native executable is required')
    if args.starts<5 or args.samples<500 or args.warmups<1:raise ValueError('at least 5 fresh starts, 500 HTTP samples and a warmup are required')
    process=None;starts=[];memory=[];conditioning={}
    original=os.environ.get('SIERX_BENCH_URL')
    original_client=bench.Client
    class LoopbackClient(original_client):
        def __init__(self,base):
            super().__init__(base)
            import http.cookiejar
            import urllib.parse
            expected=urllib.parse.urlsplit(base).netloc
            class LocalPolicy(http.cookiejar.DefaultCookiePolicy):
                def return_ok_secure(self,cookie,request):
                    # Explicit collector-created loopback process only. General
                    # bench-http still requires secure cookies over HTTPS.
                    return urllib.parse.urlsplit(request.full_url).netloc==expected
            self.jar.set_policy(LocalPolicy())
    try:
        for _ in range(args.starts):
            stop(process);process,base,elapsed=start(binary);starts.append(elapsed)
        os.environ['SIERX_BENCH_URL']=base;bench.Client=LoopbackClient
        args.sample_observer=lambda:memory.append(rss_bytes(process.pid))
        def workload_warmup(client,scenarios):
            conditioning.update(condition(client,scenarios,lambda:rss_bytes(process.pid)))
        args.workload_warmup=workload_warmup
        http_report=bench.run(args)
        if len(memory)!=args.samples*len(bench.LIMITS_MS):raise ValueError('RSS measurement did not cover every measured scenario')
        return {'measurement':'fresh process readiness and RSS during authenticated warmed 10k HTTP workload',
                'binary_sha256':hashlib.sha256(binary.read_bytes()).hexdigest(),'target_label':http_report['target_label'],
                'hardware':http_report['hardware'],'active_fixture_items':http_report['active_fixture_items'],
                'cold_start':{'samples':len(starts),'p50_ms':round(bench.percentile(starts,.5),3),
                              'p95_ms':round(bench.percentile(starts,.95),3),'max_ms':round(max(starts),3),
                              'limit_ms':COLD_LIMIT_MS,'within_limit':max(starts)<COLD_LIMIT_MS},
                'conditioning':conditioning,
                'rss':{'samples':len(memory),'p50_bytes':bench.percentile(memory,.5),'p95_bytes':bench.percentile(memory,.95),
                       'max_bytes':max(memory),'limit_bytes':RSS_LIMIT,'within_limit':max(memory)<RSS_LIMIT},
                'http_results':http_report['results'],
                'note':'Fresh processes; OS page cache is retained. Steady RSS samples follow a fixed ten-second authenticated workload, independent of the budget. Conditioning RSS peak is reported separately; transient password verification allocations can exceed the steady limit. /proc reads occur after request timing. Loopback HTTP excludes TLS/tunnel costs. Review limits on chosen reference hardware.'}
    finally:
        stop(process);bench.Client=original_client
        if original is None:os.environ.pop('SIERX_BENCH_URL',None)
        else:os.environ['SIERX_BENCH_URL']=original

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary',required=True)
    parser.add_argument('--starts',type=int,default=10)
    parser.add_argument('--samples',type=int,default=500)
    parser.add_argument('--warmups',type=int,default=20)
    print(json.dumps(run(parser.parse_args()),indent=2))

if __name__=='__main__':
    try:main()
    except (KeyError,ValueError,OSError,TypeError,json.JSONDecodeError):
        sys.exit('bench-process: measurement failed; check Linux, accepted binary, private app/benchmark configuration and the 10k fixture')
