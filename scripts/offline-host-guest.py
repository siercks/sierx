"""Runs only as the synthetic account inside offline-host.py's disposable OS."""
import base64
import hashlib
import http.cookiejar
import json
import os
from pathlib import Path
import platform
import secrets
import ssl
import subprocess
import sys
import time
import urllib.request
import offline_host_evidence as evidence
import importlib.util
import offline_host_inputs
import ipaddress

HOME = Path(os.environ['HOME'])
BUNDLE = Path('/opt/sierx-bundle')
OPTIONS = json.loads((HOME / 'options.json').read_text())
ENV = dict(os.environ)
LOG = HOME / 'diagnostics.log'
PHASE = 'initialization'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def manager_proof():
    require(os.getuid() == 0, 'Manager namespace evidence requires the guest root preflight')
    managers = []
    for entry in Path('/proc').iterdir():
        if not entry.name.isdigit():
            continue
        try:
            if (entry/'comm').read_text().strip() == 'systemd' and b'--user' in (entry/'cmdline').read_bytes().split(b'\0'):
                managers.append(int(entry.name))
        except (FileNotFoundError,ProcessLookupError):
            pass
    require(len(managers)==1,'Exactly one real user manager is required')
    manager = managers[0]
    status = Path(f'/proc/{manager}/status').read_text()
    uids = next(line.split()[1:] for line in status.splitlines() if line.startswith('Uid:'))
    proof = {'manager_net':os.readlink(f'/proc/{manager}/ns/net'),
             'system_net':os.readlink('/proc/1/ns/net'), 'manager_uids':uids}
    descriptor = os.open(HOME / 'manager-proof.json', os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
    with os.fdopen(descriptor,'w') as stream:
        json.dump(proof,stream)
    if OPTIONS['closeout']:
        hashes=offline_host_inputs.invalid_bundles(BUNDLE,Path('/opt/invalid-bundles'))
        descriptor=os.open(HOME/'invalid-inputs.json',os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o644)
        with os.fdopen(descriptor,'w') as stream:json.dump(hashes,stream)


def phase(name):
    global PHASE
    PHASE = name
    (HOME / 'progress.json').write_text(json.dumps({'phase': name}))
    print('SIERX_PHASE: ' + name, flush=True)


def run(*args, env=None):
    with LOG.open('ab') as log:
        result = subprocess.run(list(map(str, args)), stdout=subprocess.PIPE, stderr=log,
                                env=env or ENV, cwd=BUNDLE,
                                timeout=1800 if PHASE=='import' and OPTIONS['virtual_cpu']=='tcg' else 600)
        log.write(result.stdout)
    if result.returncode:
        raise RuntimeError('Fixture command failed in ' + PHASE)
    return result.stdout.decode().strip()


def operation(name, bundle=BUNDLE, expected=None):
    return run('python3', '-B', bundle / 'scripts/offline.py', name,
               env={**ENV, 'SIERX_OFFLINE_BUNDLE': str(bundle),
                    'SIERX_OFFLINE_SHA256': expected or OPTIONS['bundle_sha256']})


def await_database():
    for attempt in range(60):
        try:
            if run('psql', ENV['DATABASE_URL'], '-XAt', '-v', 'ON_ERROR_STOP=1', '-c', 'SELECT 1') == '1':
                return
        except RuntimeError:
            pass
        time.sleep(1)
    raise RuntimeError('Database TCP endpoint did not become ready')


def main():
    os.umask(0o077)
    require(os.getuid() == 1001, 'Guest fixture requires the unprivileged synthetic account')
    require(Path('/proc/1/comm').read_text().strip() == 'systemd', 'Guest system manager is not real systemd')
    require(any(line in {'0::/', '0::/init.scope'} for line in Path('/proc/1/cgroup').read_text().splitlines()),
            'Guest system manager lacks its own unified cgroup namespace')
    # The real user manager must share the guest's isolated network namespace.
    interfaces = json.loads(run('ip', '-j', 'link', 'show'))
    require({entry['ifname'] for entry in interfaces} == {'lo'}, 'Guest networking is not loopback-only')
    proof = json.loads((HOME / 'manager-proof.json').read_text())
    require(proof['manager_uids'] == ['1001'] * 4, 'Systemd user manager has the wrong identity')
    require(proof['manager_net'] == proof['system_net'] == os.readlink('/proc/self/ns/net'), 'User manager escaped guest network namespace')
    info = json.loads(run('podman', 'info', '--format', 'json'))
    require(info['host']['security']['rootless'] is True, 'Podman is not rootless')
    require(info['host']['cgroupManager'] == 'systemd', 'Real systemd cgroup delegation is missing')
    require(info['store']['imageStore']['number'] == 0, 'Image store is not fresh')
    require(info['store']['graphDriverName'] == 'overlay', 'Native rootless overlay storage is required')
    profile = platform.freedesktop_os_release()
    phase('import')
    password = secrets.token_urlsafe(32)
    database = 'postgres://sierx:' + password + '@127.0.0.1:15432/sierx?sslmode=disable'
    ENV.update(DATABASE_URL=database,
               SIERX_RUNTIME_DATABASE_URL=database.replace('sierx:', 'sierx_runtime:', 1),
               SIERX_AUTH_DATABASE_URL=database.replace('sierx:', 'sierx_auth:', 1),
               SIERX_MAINTENANCE_DATABASE_URL=database.replace('sierx:', 'sierx_maintenance:', 1),
               SIERX_ENV='staging', SIERX_AUTH_MODE='local', SIERX_BASE_URL='https://localhost:18443',
               SIERX_APP_PORT='18081', SIERX_LISTEN_ADDR='127.0.0.1:18081',
               SIERX_SESSION_KEY=base64.b64encode(secrets.token_bytes(32)).decode(),
               SIERX_TLS_MODE='provided', SIERX_GATEWAY_MODE='direct', SIERX_NETWORK_MODE='offline',
               SIERX_BOOTSTRAP_ADMIN_EMAIL='offline@example.test',
               SIERX_BOOTSTRAP_ADMIN_PASSWORD=password, SIERX_BOOTSTRAP_ADMIN_NAME='Offline acceptance',
               SIERX_BOOTSTRAP_WORKSPACE_SLUG='offline', SIERX_BOOTSTRAP_WORKSPACE_NAME='Offline acceptance',
               SIERX_BOOTSTRAP_PROJECT_PREFIX='SRX', SIERX_BOOTSTRAP_PROJECT_NAME='Backlog')
    operation('import')
    phase('rootless-database')
    operation('db-up')
    await_database()
    database_container=json.loads(run('podman','inspect','sierx-postgres'))[0]
    require(database_container['HostConfig']['NetworkMode']=='slirp4netns', 'Database requires the explicit no-NIC rootless network backend')
    phase('migration-bootstrap')
    operation('migrate-up')
    operation('bootstrap')
    guard = HOME / '.local/share/sierx/lifecycle/guard'
    guard.mkdir(mode=0o700, parents=True)
    ENV.update(SIERX_LIFECYCLE_JOURNAL=str(guard.parent / 'journal.jsonl'),
               SIERX_LIFECYCLE_KEY_FILE=str(guard.parent / 'master.key'),
               SIERX_LIFECYCLE_CHECKPOINT=str(guard / 'checkpoint.json'))
    run(BUNDLE / 'bin/sierxctl', 'lifecycle', 'init')
    config = HOME / '.config/sierx'
    tls = config / 'tls'
    tls.mkdir(parents=True)
    ca=HOME/'fixture-ca'
    ca.mkdir(mode=0o700)
    run('openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1',
        '-keyout',ca/'ca.key','-out',ca/'ca.crt','-subj','/CN=Sierx fixture CA',
        '-addext','basicConstraints=critical,CA:TRUE','-addext','keyUsage=critical,keyCertSign,cRLSign')
    run('openssl','req','-new','-newkey','rsa:2048','-nodes','-keyout',tls/'server.key',
        '-out',ca/'server.csr','-subj','/CN=localhost')
    (ca/'server.ext').write_text('basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\n'
        'extendedKeyUsage=serverAuth\nsubjectAltName=DNS:localhost,IP:127.0.0.1,IP:::1\n')
    run('openssl','x509','-req','-in',ca/'server.csr','-CA',ca/'ca.crt','-CAkey',ca/'ca.key',
        '-CAcreateserial','-out',tls/'server.crt','-days','1','-extfile',ca/'server.ext')
    (tls / 'server.key').chmod(0o600)
    ENV['SSL_CERT_FILE'] = str(ca/'ca.crt')
    ENV['SIERX_TEST_SERVER_CERT']=str(tls/'server.crt')
    ENV['NODE_EXTRA_CA_CERTS'] = ENV['SSL_CERT_FILE']
    app = {key: ENV[key] for key in ('SIERX_ENV','SIERX_AUTH_MODE','SIERX_BASE_URL',
        'SIERX_LISTEN_ADDR','SIERX_SESSION_KEY','SIERX_RUNTIME_DATABASE_URL','SIERX_AUTH_DATABASE_URL')}
    app.update(SIERX_LIFECYCLE_CHECKPOINT='/var/lib/sierx/lifecycle/guard/checkpoint.json',
               SIERX_LIFECYCLE_GUARD_KEY_FILE='/var/lib/sierx/lifecycle/guard/verification.key')
    (config / 'app.env').write_text(''.join(key + '=' + value + '\n' for key,value in app.items()))
    (config / 'maintenance.env').write_text('SIERX_MAINTENANCE_DATABASE_URL=' + ENV['SIERX_MAINTENANCE_DATABASE_URL'] + '\n')
    phase('actual-plan-apply')
    operation('plan')
    operation('apply')
    phase('https-data-check')
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar),
        urllib.request.HTTPSHandler(context=ssl.create_default_context(cafile=ENV['SSL_CERT_FILE'])))
    def request(path, body=None):
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(ENV['SIERX_BASE_URL'] + path, data=data,
              headers={'Content-Type':'application/json','Origin':ENV['SIERX_BASE_URL']})
        with opener.open(req, timeout=20) as response:
            return response.read()
    request('/api/v1/auth/login', {'email':'offline@example.test','password':password})
    item = json.loads(request('/api/v1/items', {'project':'SRX','type':'story','title':'Rootless delivered item'}))
    ENV.update(SIERX_SMOKE_URL=ENV['SIERX_BASE_URL'], SIERX_SMOKE_ITEM=item['key'],
               SIERX_SMOKE_EMAIL='offline@example.test', SIERX_SMOKE_PASSWORD=password)
    before = operation('smoke')
    phase('repeat-apply')
    stamps = {name: run('podman','inspect',name,'--format','{{.State.StartedAt}}') for name in ('sierx','sierx-caddy')}
    operation('apply')
    require(stamps == {name:run('podman','inspect',name,'--format','{{.State.StartedAt}}') for name in stamps}, 'Repeated apply restarted services')
    phase('restart')
    run('systemctl','--user','restart','sierx-postgres.service')
    await_database()
    run('systemctl','--user','restart','sierx.service','sierx-caddy.service')
    for attempt in range(30):
        try:
            after = operation('smoke')
            break
        except RuntimeError:
            time.sleep(1)
    else:
        raise RuntimeError('HTTPS did not recover after real user-service restart')
    require(before == after, 'Item changed after real service restart')
    lock = json.loads((BUNDLE / 'bundle.lock.json').read_text())
    phase('network-negative-controls')
    spec = importlib.util.spec_from_file_location('network_controls', '/opt/acceptance/tests/offline-network-controls.py')
    controls = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(controls)
    controls.main(ENV,lock,run,phase)
    phase('delivered-browser-workflows')
    # Confine only the JavaScript test driver and its browsers to observable
    # socket syscalls. Shipped app/database/gateway services keep their normal
    # profiles. libuv's epoll batching is not disabled by UV_USE_IO_URING=0.
    command=['systemd-run','--user','--unit=sierx-browser-acceptance','--wait','--pipe','--quiet','--collect',
             '--property=Type=exec','--property=SystemCallFilter=~io_uring_setup io_uring_enter io_uring_register',
             '--property=SystemCallErrorNumber=ENOSYS',
             '--property=RestrictAddressFamilies=AF_UNIX AF_INET AF_NETLINK']
    for name in ('HOME','PATH','PLAYWRIGHT_BROWSERS_PATH','SIERX_BASE_URL','SSL_CERT_FILE','NODE_EXTRA_CA_CERTS',
                 'SIERX_BOOTSTRAP_ADMIN_EMAIL','SIERX_BOOTSTRAP_ADMIN_PASSWORD','SIERX_TEST_SERVER_CERT'):
        command.append('--setenv='+name+'='+ENV[name])
    browser = json.loads(run(*command,'/usr/local/bin/node','/opt/acceptance/tests/offline-browser.mjs'))
    evidence.validate_browser(browser)
    scenarios = {}
    if OPTIONS['closeout']:
        spec=importlib.util.spec_from_file_location('host_scenarios','/opt/acceptance/tests/offline-host-scenarios.py')
        scenario=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(scenario)
        phase('invalid-deliveries')
        OPTIONS['invalid_hashes']=json.loads((HOME/'invalid-inputs.json').read_text())
        scenarios['invalid_deliveries']=scenario.delivery_failures(BUNDLE,OPTIONS,ENV,run,LOG)
        phase('two-approved-releases')
        scenarios['two_release']=scenario.two_release(BUNDLE,OPTIONS,ENV,operation,run,require)
        phase('failed-health-rollback')
        scenarios['failed_health']=scenario.failed_health(BUNDLE,ENV,operation,run,LOG)
        phase('bounded-runtime')
        request('/api/v1/auth/login',{'email':'offline@example.test','password':password})
        scenarios['runtime']=scenario.runtime(BUNDLE,OPTIONS['soak_seconds'],ENV,run,LOG,request)
        phase('explicit-opt-in-acquisition')
        spec=importlib.util.spec_from_file_location('registry','/opt/acceptance/tests/offline-local-registry.py')
        registry=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(registry)
        scenarios['acquisition']=registry.main(BUNDLE,lock,ENV,run)
    addresses = json.loads(run('podman','inspect','sierx-postgres'))[0]['NetworkSettings'].get('Networks') or {}
    peers=run('psql',ENV['DATABASE_URL'],'-XAt','-v','ON_ERROR_STOP=1','-c',
        "SELECT host(inet_client_addr()) UNION SELECT host(inet_server_addr()) UNION SELECT host(client_addr) FROM pg_stat_activity WHERE datname=current_database() AND client_addr IS NOT NULL").splitlines()
    peers += [entry[key] for entry in addresses.values() for key in ('IPAddress','Gateway') if entry.get(key)]
    internal=set()
    for value in peers:
        address=ipaddress.ip_address(value)
        address=getattr(address,'ipv4_mapped',None) or address
        if not address.is_loopback:internal.add(address.compressed)
    enforcement=Path('/sys/fs/selinux/enforce')
    selinux=('enforcing' if enforcement.read_text().strip()=='1' else 'permissive') if enforcement.exists() else 'disabled'
    versions={'kernel':platform.release(),'systemd':run('systemctl','--version').splitlines()[0],
              'podman':run('podman','--version'),'selinux':selinux}
    phase('complete')
    return {'schema': evidence.SCHEMA, 'suite':evidence.SUITE, 'suite_sha256':OPTIONS['suite_sha256'],
            'result':'passed', 'profile':profile['ID'] + '-' + profile['VERSION_ID'],
            'arch':lock['arch'], 'release':lock['release'], 'bundle_sha256':OPTIONS['bundle_sha256'],
            'isolation':evidence.ISOLATION, 'checks':evidence.CHECKS + (evidence.CLOSEOUT_CHECKS if OPTIONS['closeout'] else []),
            'coverage':'closeout' if OPTIONS['closeout'] else 'development','browser':browser,
            'internal_addresses':sorted(internal),'scenarios':scenarios,'host_versions':versions}


if __name__ == '__main__':
    if sys.argv[1:] == ['--manager-proof']:
        manager_proof()
        sys.exit(0)
    try:
        result = main()
    except Exception as error:
        with LOG.open('a') as log:
            log.write('\nFailed phase: ' + PHASE + '\n' + type(error).__name__ + ': ' + str(error) + '\n')
        result = {'result':'failed','phase':PHASE,'failure_type':type(error).__name__}
        for name in ('sierx-postgres.service','sierx.service','sierx-caddy.service'):
            with LOG.open('ab') as log:
                try:
                    subprocess.run(['journalctl','--user','--no-pager','-u',name,'-n','40'],stdout=log,stderr=log,timeout=10)
                except subprocess.TimeoutExpired:
                    log.write(b'Private journal collection timed out\n')
    (HOME / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    os.sync()
    print('SIERX_FINISHED: '+OPTIONS['suite_sha256']+' '+result['result'],flush=True)
    sys.exit(0 if result['result'] == 'passed' else 1)
