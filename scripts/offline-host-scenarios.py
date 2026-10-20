"""Real installer failure, retained-release and bounded runtime scenarios.

Only the disposable acceptance account calls this module. Fixture faults are
explicitly synthetic and never count as a second approved release.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import secrets
import threading
import urllib.request
import re
from offline_host_evidence import DATA_TABLES
from offline_host_inputs import isolated_storage, require_empty_storage


HOME = Path(os.environ['HOME'])
CONFIG = HOME / '.config/sierx'
STATE = HOME / '.local/share/sierx'


def backlog_fingerprint(env,run):
    # Session activity is expected to change during login. Capture every stable
    # backlog/configuration/profile row and counter without printing contents.
    queries=[]
    for name in DATA_TABLES:
        query=("SELECT '"+name+"' AS table_name, count(*)::text||':'||md5(coalesce(jsonb_agg(record_json ORDER BY record_json::text)::text,'[]')) AS fingerprint "
               'FROM (SELECT to_jsonb(t) AS record_json FROM public."'+name+'" AS t) records')
        queries.append(query)
    # One transaction gives every table the same snapshot and avoids starting
    # a separate database client for each table under the syscall observer.
    query='SELECT jsonb_object_agg(table_name,fingerprint) FROM ('+' UNION ALL '.join(queries)+') fingerprints'
    values=json.loads(run('psql',env['DATABASE_URL'],'-XAt','-v','ON_ERROR_STOP=1','-c',query))
    if set(values)!=set(DATA_TABLES):raise ValueError('Incomplete stable-data fingerprint')
    return hashlib.sha256(json.dumps(values,sort_keys=True).encode()).hexdigest()


def smoke_fingerprint(output):
    match=re.search(r'item fingerprint ([a-f0-9]{64})',output)
    if not match:raise ValueError('Real HTTPS smoke did not return its required item fingerprint')
    return match[1]


def rejection(args, env, log):
    with log.open('ab') as stream:
        result = subprocess.run(list(map(str,args)),env=env,stdout=stream,stderr=stream,
                                timeout=1800 if env.get('SIERX_TEST_EMULATED')=='1' else 180)
    if result.returncode == 0:
        raise ValueError('Deliberately invalid delivery unexpectedly succeeded')


def installer(bundle, operation, expected, env, log):
    rejection(['python3','-B',bundle/'scripts/offline.py',operation],
              {**env,'SIERX_OFFLINE_BUNDLE':str(bundle),'SIERX_OFFLINE_SHA256':expected},log)


def service_snapshot(run):
    paths = [HOME/'.config/containers/systemd'/name for name in ('sierx.container','sierx-caddy.container')]
    paths += [CONFIG/'Caddyfile', STATE/'current.json']
    return {'files':{str(path):hashlib.sha256(path.read_bytes()).hexdigest() for path in paths},
            'started':{name:run('podman','inspect',name,'--format','{{.State.StartedAt}}') for name in ('sierx','sierx-caddy')}}


def delivery_failures(bundle, options, env, run, log):
    before = service_snapshot(run)
    for name in ('missing-image','altered-archive','wrong-architecture'):
        fixture = Path('/opt/invalid-bundles')/name
        installer(fixture,'import',options['invalid_hashes'][name],env,log)
    installer(bundle,'import','0'*64,env,log)
    certificate = CONFIG/'tls/server.crt'
    parked = certificate.with_suffix('.parked')
    certificate.rename(parked)
    try:
        installer(bundle,'plan',options['bundle_sha256'],env,log)
    finally:
        parked.rename(certificate)
    # A separate empty image store exercises actual no-pull plan rejection.
    storage,runroot = HOME/'empty-store',Path(env['XDG_RUNTIME_DIR'])/'empty-store'
    isolated=isolated_storage(storage,runroot,env)
    require_empty_storage(json.loads(run('podman','info','--format','json',env=isolated)),storage,runroot)
    installer(bundle,'plan',options['bundle_sha256'],isolated,log)
    if service_snapshot(run) != before:
        raise ValueError('Rejected delivery changed the accepted revision or running services')
    return ['missing-image','altered-archive','wrong-architecture','wrong-digest','missing-certificate','empty-image-store']


def two_release(bundle, options, env, operation, run, require):
    previous = Path('/opt/previous-bundle')
    old = json.loads((previous/'bundle.lock.json').read_text())
    new = json.loads((bundle/'bundle.lock.json').read_text())
    require(old['release']['revision'] != new['release']['revision'], 'Two approved revisions are required')
    def database():
        return run('psql',env['DATABASE_URL'],'-XAt','-v','ON_ERROR_STOP=1','-c',
            "SELECT coalesce(max(version_id) FILTER(WHERE is_applied),0) FROM goose_db_version")
    fingerprint = smoke_fingerprint(operation('smoke'))
    rows=backlog_fingerprint(env,run)
    schema = database()
    operation('import',previous,options['previous_sha256'])
    operation('apply',previous,options['previous_sha256'])
    require(smoke_fingerprint(operation('smoke',previous,options['previous_sha256'])) == fingerprint, 'Previous approved release cannot read current schema/data')
    operation('apply',bundle,options['bundle_sha256'])
    operation('migrate-up',bundle,options['bundle_sha256'])
    require(smoke_fingerprint(operation('smoke')) == fingerprint and database() == schema and backlog_fingerprint(env,run)==rows,'Offline update changed existing data or schema unexpectedly')
    operation('apply',previous,options['previous_sha256'])
    require(smoke_fingerprint(operation('smoke',previous,options['previous_sha256'])) == fingerprint and database() == schema and backlog_fingerprint(env,run)==rows,'Compatible rollback failed')
    operation('apply',bundle,options['bundle_sha256'])
    require(smoke_fingerprint(operation('smoke')) == fingerprint and backlog_fingerprint(env,run)==rows,'Candidate did not recover after rollback')
    return {'previous':old['release'], 'previous_bundle_sha256':options['previous_sha256'], 'candidate':new['release'], 'schema_before':int(schema),
            'schema_after':int(database()), 'fingerprint_preserved':True,
            'update':True, 'compatible_rollback':True,'data_scope':DATA_TABLES}


def failed_health(bundle, env, operation, run, log):
    """Break the delivered executable, without modifying installer or live config."""
    before = service_snapshot(run)
    fingerprint = smoke_fingerprint(operation('smoke'))
    rows=backlog_fingerprint(env,run)
    revision = secrets.token_hex(20)
    name = 'sierx-unhealthy-fixture'
    old = json.loads((bundle/'bundle.lock.json').read_text())
    container = run('podman','create','--pull=never',old['images']['app']['id'])
    try:
        image = run('podman','commit','--change','LABEL org.opencontainers.image.revision='+revision,container,name)
    finally:
        run('podman','rm',container)
    if not image.startswith('sha256:'):
        image = 'sha256:'+image
    fixture = HOME/'failed-health-bundle'
    # --reflink=auto preserves space without hard-linking writable files to the
    # approved read-only input. Failure fixtures cannot alter the trusted bundle.
    run('cp','--recursive','--preserve=mode,timestamps','--reflink=auto',bundle,fixture)
    for path in fixture.rglob('*'):
        if path.is_dir(): path.chmod(0o700)
        elif path.is_file(): path.chmod(0o700 if path.stat().st_mode & 0o111 else 0o600)
    archive = fixture/'images/app.tar'
    archive.unlink()
    run('podman','save','--format','oci-archive','--output',archive,image)
    release = {'image':old['release']['image'].split('@')[0]+'@'+image,'revision':revision}
    (fixture/'release.json').write_text(json.dumps(release))
    template=fixture/'deploy/quadlet/sierx.container.tmpl'
    template.write_text(template.read_text().replace('EnvironmentFile=',
        'Environment=SIERX_LISTEN_ADDR=127.0.0.1:18082\nEnvironmentFile=',1))
    old['release'] = release
    old['images']['app'].update(source=release['image'],id=image)
    for name in ('release.json','images/app.tar','deploy/quadlet/sierx.container.tmpl'):
        path = fixture/name
        with path.open('rb') as stream: digest = hashlib.file_digest(stream,'sha256').hexdigest()
        old['files'][name] = {'sha256':digest,'size':path.stat().st_size}
    lock = fixture/'bundle.lock.json'
    lock.write_text(json.dumps(old))
    expected = hashlib.sha256(lock.read_bytes()).hexdigest()
    # Validation and planning must succeed. An early verification rejection
    # cannot masquerade as a successful failed-health rollback scenario.
    operation('plan',fixture,expected)
    healthy_at_wrong_port=threading.Event()
    stop=threading.Event()
    def watch():
        while not stop.is_set():
            try:
                with urllib.request.urlopen('http://127.0.0.1:18082/api/v1/healthz',timeout=1) as response:
                    if response.status==200:healthy_at_wrong_port.set()
            except OSError:pass
            stop.wait(0.25)
    watcher=threading.Thread(target=watch,daemon=True)
    watcher.start()
    started=str(int(time.time()))
    try:
        installer(fixture,'apply',expected,env,log)
    finally:
        stop.set()
        watcher.join(timeout=3)
    events=[json.loads(line) for line in run('podman','events','--stream=false','--since',started,'--format','json').splitlines()]
    launched=any(event.get('Type')=='container' and event.get('Status')=='start'
        and event.get('Attributes',{}).get('org.opencontainers.image.revision')==revision for event in events)
    if not launched or not healthy_at_wrong_port.is_set():
        raise ValueError('Failed-health fixture never started the healthy candidate at its deliberately wrong port')
    # A rollback necessarily restarts services; the retained configuration and
    # acceptance record must remain byte-for-byte identical.
    after = service_snapshot(run)
    if before['files'] != after['files']:
        raise ValueError('Failed health advanced acceptance or failed to restore previous service configuration')
    for attempt in range(30):
        try:
            if smoke_fingerprint(operation('smoke')) == fingerprint and backlog_fingerprint(env,run)==rows:
                return {'rejected':True,'candidate_started':True,'candidate_health_failed':True,
                        'accepted_revision_preserved':True,'configuration_restored':True,'data_preserved':True}
        except RuntimeError:
            pass
        time.sleep(1)
    raise ValueError('Previous release did not recover automatically after failed health')


def runtime(bundle, seconds, env, run, log, request, progress=None):
    if not 120 <= seconds <= 180:
        raise ValueError('Runtime observation must last between 120 and 180 seconds')
    def step(name):
        if progress is not None:progress('runtime-'+name)
    step('reject-implicit-timers')
    # The real timer installer must reject every implicit offline schedule.
    for mode in ('install-timer','install-backup-timer','install-maintenance-timer','install-restore-timer','install-lifecycle-timer'):
        rejection(['python3','-B',bundle/'scripts/deploy.py',mode],env,log)
    units = HOME/'.config/systemd/user'
    units.mkdir(parents=True,exist_ok=True)
    # This explicit local-only fixture schedule runs the shipped maintenance
    # command. It does not weaken the production offline timer prohibition.
    (units/'sierx-maintenance.service').write_text((bundle/'deploy/quadlet/sierx-maintenance.service').read_text())
    (units/'sierx-acceptance-maintenance.timer').write_text('''[Unit]
Description=Explicit synthetic acceptance schedule
[Timer]
OnActiveSec=2s
AccuracySec=100ms
Unit=sierx-maintenance.service
''')
    step('reload-units')
    run('systemctl','--user','daemon-reload')
    step('start-timer')
    run('systemctl','--user','start','sierx-acceptance-maintenance.timer')
    step('observe')
    started = time.monotonic()
    polls = 0
    while time.monotonic()-started < seconds:
        request('/api/v1/healthz')
        request('/api/v1/changes?since_seq=0')
        polls += 1
        time.sleep(5)
    step('verify-maintenance')
    if run('systemctl','--user','show','sierx-maintenance.service','--property=Result','--value') != 'success':
        raise ValueError('Accelerated local maintenance failed')
    timestamp = run('systemctl','--user','show','sierx-maintenance.service','--property=ExecMainStartTimestampMonotonic','--value')
    if timestamp == '0':
        raise ValueError('Accelerated timer never triggered the shipped service')
    step('inventory-services')
    services = json.loads(run('systemctl','--user','list-units','--all','--type=service','--output=json','--no-pager'))
    step('inventory-timers')
    timers = json.loads(run('systemctl','--user','list-timers','--all','--output=json','--no-pager'))
    step('inventory-enabled')
    enabled = run('systemctl','--user','list-unit-files','--state=enabled','--no-legend','--no-pager')
    if 'sierx-pull.timer' in enabled:
        raise ValueError('An automatic acquisition timer was enabled offline')
    return {'seconds':seconds,'elapsed_seconds':round(time.monotonic()-started,3),'change_feed_polls':polls,'maintenance_timer_triggered':True,
            'offline_timer_modes_rejected':5,
            'services':sorted(entry['unit'] for entry in services),
            'timers':sorted(entry['unit'] for entry in timers),
            'enabled_units':sorted(line.split()[0] for line in enabled.splitlines())}
