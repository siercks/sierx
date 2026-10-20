"""Synthetic, explicitly labelled failed network attempts inside the no-NIC guest.

These controls exercise the actual delivered executables. They are never run
on an operator host or against production data.
"""
import json
import os
from pathlib import Path
import socket
import signal
import subprocess
import time
import urllib.request


HOME = Path(os.environ['HOME'])
CONTROLS = HOME / 'network-controls.json'


def command(*args, timeout=15, env=None):
    process=subprocess.Popen(list(map(str,args)),env=env,stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE,start_new_session=True)
    try:
        stdout,stderr=process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid,signal.SIGKILL)
        process.stdout.close()
        process.stderr.close()
        process.wait(timeout=5)
        raise ValueError('Synthetic network command exceeded its bounded timeout')
    return subprocess.CompletedProcess(args,process.returncode,stdout,stderr)


def record(name, action, aliases=(), timeout=20):
    start = time.time()
    try:
        action()
    finally:
        end = time.time()
        entries = json.loads(CONTROLS.read_text()) if CONTROLS.exists() else []
        entries.extend({'name':value, 'start':start, 'end':end} for value in (name,*aliases))
        CONTROLS.write_text(json.dumps(entries))
    if end-start > timeout:
        raise ValueError('Network negative control exceeded its bounded interval')


def require_failure(result):
    if result.returncode == 0:
        raise ValueError('Planted forbidden connection unexpectedly succeeded')


def main(env, lock, run, phase):
    if os.getuid() != 1001 or {entry['ifname'] for entry in json.loads(run('ip','-j','link','show'))} != {'lo'}:
        raise ValueError('Network controls require the isolated synthetic guest')
    emulated = env.get('SIERX_TEST_EMULATED') == '1'
    interval = 120 if emulated else 20
    command_timeout = 60 if emulated else 15
    app_env = HOME / '.config/sierx/app.env'
    bad_env = HOME / 'network-control.env'
    text = app_env.read_text()
    for key in ('SIERX_RUNTIME_DATABASE_URL','SIERX_AUTH_DATABASE_URL'):
        lines = text.splitlines()
        role = 'sierx_runtime' if key == 'SIERX_RUNTIME_DATABASE_URL' else 'sierx_auth'
        text = '\n'.join(key+'=postgres://'+role+':synthetic@198.51.100.11:18181/denied?sslmode=disable&connect_timeout=1'
                         if line.startswith(key+'=') else line for line in lines)+'\n'
    bad_env.write_text(text)
    phase('negative-app')
    def app():
        run('podman','--cgroup-manager=cgroupfs','run','--detach','--name','sierx-app-control',
            '--cgroups=disabled','--pull=never','--network=host','--userns=keep-id:uid=65532,gid=65532',
            '--volume',str(HOME/'.local/share/sierx/lifecycle/guard')+':/var/lib/sierx/lifecycle/guard:ro,z',
            '--env-file',bad_env,lock['images']['app']['id'])
        result=command('podman','--cgroup-manager=cgroupfs','wait','sierx-app-control',timeout=60 if emulated else 10)
        if result.returncode or result.stdout.strip()==b'0':
            raise ValueError('Synthetic application must fail on its forbidden database connection')
    try:
        record('app-tcp',app,timeout=interval)
    finally:
        run('podman','--cgroup-manager=cgroupfs','rm','--force','--ignore','sierx-app-control')
        bad_env.unlink(missing_ok=True)

    config = HOME / 'network-control.Caddyfile'
    config.write_text('''{
  admin off
  auto_https off
}
http://127.0.0.1:19443 {
  reverse_proxy 198.51.100.12:18181 {
    transport http {
      dial_timeout 1s
    }
  }
}
''')
    phase('negative-gateway')
    run('podman','--cgroup-manager=cgroupfs','run','--detach','--name','sierx-network-control','--pull=never','--network=host','--cgroups=disabled',
        '--volume',str(config)+':/etc/caddy/Caddyfile:ro,Z',lock['images']['caddy']['id'])
    try:
        def gateway():
            for attempt in range(20):
                result = command('curl','--silent','--show-error','--fail','--max-time','1','http://127.0.0.1:19443',timeout=command_timeout)
                if result.returncode != 7:
                    require_failure(result)
                    return
                time.sleep(0.1)
            raise ValueError('Gateway negative-control listener did not start')
        record('gateway-tcp', gateway,timeout=interval)
    finally:
        run('podman','--cgroup-manager=cgroupfs','logs','sierx-network-control')
        run('podman','--cgroup-manager=cgroupfs','rm','--force','sierx-network-control')
        config.unlink(missing_ok=True)

    phase('negative-database')
    run('psql',env['DATABASE_URL'],'-XAt','-v','ON_ERROR_STOP=1','-c','CREATE EXTENSION dblink')
    try:
        record('database-tcp', lambda: require_failure(command('psql',env['DATABASE_URL'],'-XAt',
            '-v','ON_ERROR_STOP=1','-c',"SELECT dblink_connect('hostaddr=198.51.100.13 port=18181 dbname=denied user=denied connect_timeout=1')",timeout=command_timeout)),aliases=('database-proxy-tcp',),timeout=interval)
    finally:
        run('psql',env['DATABASE_URL'],'-XAt','-v','ON_ERROR_STOP=1','-c','DROP EXTENSION dblink')

    def fetch():
        try:
            urllib.request.build_opener(urllib.request.ProxyHandler({})).open('http://198.51.100.14:18181',timeout=2)
        except OSError:
            return
        raise ValueError('Forbidden installer fetch succeeded')
    phase('negative-installer')
    record('installer-fetch', fetch,timeout=interval)
    record('registry-pull',lambda: require_failure(command('podman','pull','--tls-verify=false',
        '198.51.100.14:18182/forbidden/control:unavailable',timeout=command_timeout)),timeout=interval)
    def packet(family, address, port, udp=False):
        with socket.socket(family,socket.SOCK_DGRAM if udp else socket.SOCK_STREAM) as client:
            client.settimeout(2)
            try:
                if udp:
                    # A valid synthetic DNS question for an explicitly reserved name.
                    client.sendto(b'\x12\x34\x01\x00\x00\x01\x00\x00\x00\x00\x00\x00\x06denied\x04test\x00\x00\x01\x00\x01',(address,port))
                else:
                    client.connect((address,port))
            except OSError:
                return
            raise ValueError('Forbidden packet unexpectedly left the guest')
    phase('negative-dns-ipv-six')
    record('dns-udp',lambda: packet(socket.AF_INET,'198.51.100.16',53,True),timeout=interval)
    record('ipv6-tcp',lambda: packet(socket.AF_INET6,'2001:db8::16',18181),timeout=interval)
