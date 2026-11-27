"""Allowlisted VM failure metadata; never a passing acceptance report."""
from collections import deque
import http.client
import json
import os
from pathlib import Path
import re
import runpy
import signal
import ssl
import subprocess
import sys
import tempfile
import traceback
import urllib.error
from kernel_network_evidence import SCHED_PROCESS_EXIT
from network_observer import safe_failure_fields
import offline_apply_trace
import offline_host_evidence
import offline_import_trace
import offline_smoke_trace

INSTALLER_EXIT_TRACE = Path('/sys/kernel/tracing/instances/sierx-installer-exit')
INSTALLER_MARKER_FD = 4
INSTALLER_OPERATIONS = {'import', 'db-up', 'migrate-up', 'bootstrap', 'plan', 'apply', 'smoke'}
IMPORT_ROLES = ('app', 'caddy', 'postgres')
IMPORT_STAGES = ('verify-bundle',) + tuple(
    stage + '-' + role for role in IMPORT_ROLES for stage in ('load', 'inspect')
) + ('import-complete',)
EXIT_ROLES = {'tracer', 'installer', 'import-helper'}
EXIT_TRACE_RESULTS = {'observed', 'unavailable', 'lost-events', 'invalid-records'}
EXIT_TRACE_LINE = re.compile(r'^\s*.+-(\d+)\s+\[\d+\]\s+\S+\s+(\d+\.\d+):\s+(.*)$')
TRACER_ERROR_CALLS = {'ptrace', 'wait4', 'waitid', 'write', 'writev'}
TRACER_RETURN = re.compile(r'sys_(ptrace|wait4|waitid|write|writev) -> ((?:0x)?[0-9a-f]+|-\d+)')

RESOURCE_KEYS = {'disk_available_bytes', 'memory_available_bytes', 'oom_kills',
                 'manager_trace_bytes', 'installer_trace_bytes'}
SERVICE_RESULTS = {'success', 'resources', 'timeout', 'exit-code', 'signal',
                   'core-dump', 'watchdog', 'start-limit-hit', 'oom-kill',
                   'exec-condition', 'protocol', 'unknown'}
EXIT_KINDS = {'exited', 'killed', 'dumped', 'unknown'}
SIGNALS = {entry.name.removeprefix('SIG') for entry in signal.Signals}
FAILURE_TYPES = {'TimeoutExpired', 'TimeoutError', 'ValueError', 'RuntimeError', 'PermissionError',
                 'FileNotFoundError', 'JSONDecodeError', 'UnicodeDecodeError',
                 'TypeError', 'KeyError', 'AttributeError', 'AssertionError', 'OSError',
                 'NetworkObservationError', 'HostCommandError', 'HostLaunchError', 'IndexError',
                 'BrokenPipeError', 'ServiceExit'}
FRAME_FILES = {'offline-host-guest.py','offline-host-scenarios.py','offline-local-registry.py',
               'offline_host_diagnostics.py','offline_host_inputs.py','offline_host_evidence.py',
               'offline-network-controls.py','offline.py','offline_guest_tracer.py','offline_guest_podman.py',
               'offline_import_trace.py'}
OBSERVER_FLAGS = {'ptrace','seccomp','wait','io-error','permission-denied','no-child',
                  'unexpected-wait','other-error'}
HOST_TOOLS = {'tar','mkfs.ext4','debugfs','unknown'}
HOST_DETAILS = {'storage-full','permission-denied','out-of-memory'}
HOST_LAUNCH_REASONS = {'startup-deadline', 'vm-deadline', 'completion-suite-mismatch'}
PREPARATION_STAGES = {'identify-fixture', 'pull-os', 'pull-node', 'inspect-images', 'build-inputs',
                      'pull-runtime-compiler', 'build-compatible-runtime',
                      'build-os', 'create-export-container', 'export-os', 'hash-os', 'cleanup'}
BUILD_STAGES = {'os-packages', 'postgres-client', 'npm-dependencies', 'browser-install',
                'certificate-tools', 'guest-kernel', 'uid-mapping'}
HTTPS_STEPS = {'login', 'create-item'}
HTTPS_TRANSPORT_ERRORS = (
    (TimeoutError, 'timeout'), (ssl.SSLCertVerificationError, 'certificate'),
    (ssl.SSLError, 'tls'), (http.client.RemoteDisconnected, 'disconnected'),
    (ConnectionError, 'connection'), (http.client.HTTPException, 'http-protocol'),
    (OSError, 'transport'),
)
HTTPS_FAILURE_KINDS = {'http-status', 'url-error'} | {label for _, label in HTTPS_TRANSPORT_ERRORS}
GUEST_COMMANDS = {'podman-info','podman-inspect','podman-pull'}
GUEST_COMMAND_DETAILS = {'storage-configuration','database-lock','permission-denied',
                         'storage-full','resource-unavailable','namespace-clone',
                         'reexec','deadline','unexpected-eof','tls-verification',
                         'connection-refused','manifest-unknown','other'}
DATABASE_ERROR_PATTERNS = {
    'unit-not-found':b'unit sierx-postgres.service not found',
    'start-job-failed':b'job for sierx-postgres.service failed',
    'readiness-failed':b'postgres did not become ready',
    'keyring-error':b'keyring', 'permission-denied':b'permission denied',
    'operation-not-permitted':b'operation not permitted',
    'read-only-filesystem':b'read-only file system', 'namespace-clone':b'cannot clone',
    'uid-map-failed':b'newuidmap:', 'gid-map-failed':b'newgidmap:',
    'runtime-error':b'oci runtime error', 'runtime-crun-error':b'crun: ',
    'unsupported-key':b'unsupported key', 'unrecognized-key':b'unrecognized key',
    'storage-full':b'no space left on device', 'mount-failed':b'failed to mount',
    'address-in-use':b'address already in use', 'cgroup-error':b'cgroup',
    'postgres-fatal':b'fatal:', 'selinux-denial':b'avc:  denied',
    'out-of-memory':b'out of memory',
    'network-helper-mentioned':b'slirp4netns', 'netavark-mentioned':b'netavark',
    'pasta-mentioned':b'pasta', 'conmon-mentioned':b'conmon',
    'executable-missing':b'executable file not found', 'unknown-flag':b'unknown flag',
    'overlay-helper-mentioned':b'fuse-overlayfs', 'network-namespace-mentioned':b'network namespace',
    # Static error in upstream Podman 6 libpod/networking_linux.go and
    # pkg/specgen/namespaces.go; do not infer removal from helper names alone.
    'slirp4netns-support-removed':b'slirp4netns support has been removed',
}
DATABASE_RUNTIME_COMMANDS={'podman','crun','conmon','slirp4netns','pasta','netavark','fuse-overlayfs'}
DATABASE_JOURNAL_SOURCES=DATABASE_RUNTIME_COMMANDS | {'systemd','other'}
DATABASE_JOURNAL_COUNTS=('journal_records','journal_database_unit_records',
                         'journal_runtime_error_records','journal_unclassified_error_records')
HOST_PHASES = {'host-verify-inputs','host-extract-os','host-configure-os','host-unpack-delivery',
               'host-create-filesystem','host-launch','host-read-evidence'}
DEPLOY_FAILURE_PHASES = {'actual-plan-apply', 'two-release-apply-previous',
                         'two-release-update-candidate', 'two-release-rollback',
                         'two-release-reapply-candidate'}
FAILURE_PHASES = {'initialization', 'import', 'rootless-database', 'migration-bootstrap',
                  'actual-plan-apply', 'https-data-check', 'repeat-apply', 'restart',
                  'network-negative-controls', 'negative-app', 'negative-gateway',
                  'negative-database', 'negative-installer', 'negative-dns-ipv-six',
                  'delivered-browser-workflows', 'invalid-deliveries', 'two-approved-releases',
                  'failed-health-rollback', 'bounded-runtime', 'explicit-opt-in-acquisition', 'complete',
                  'network-audit','two-release-stress-1','two-release-stress-2'} | HOST_PHASES | DEPLOY_FAILURE_PHASES | {
    'invalid-delivery-'+name for name in ('snapshot-before','missing-image','altered-archive',
        'wrong-architecture','wrong-digest','missing-certificate','empty-store-config',
        'empty-store-info','empty-store-plan','snapshot-after')} | {
    'runtime-'+name for name in ('reject-implicit-timers', 'reload-units', 'start-timer',
                                'observe', 'verify-maintenance', 'inventory-services',
                                'inventory-timers', 'inventory-enabled')} | {
    'acquisition-'+name for name in ('prepare', 'start-registry', 'store-info',
                                    'empty-store', 'pull', 'inspect', 'verify', 'stop-store')}


def sanitize_failure(value):
    """Accept fixed failure metadata only; this can never produce passing evidence."""
    if not isinstance(value, dict) or value.get('result') != 'failed':
        raise ValueError('Failure diagnostics require a failed guest result')
    result = {'result':'failed', 'phase':'unknown', 'failure_type':'unknown'}
    for key, allowed in (('phase', FAILURE_PHASES), ('failure_type', FAILURE_TYPES)):
        if isinstance(value.get(key), str) and value[key] in allowed:
            result[key] = value[key]
    code = value.get('command_exit_code')
    if type(code) is int and -128 <= code <= 255:
        result['command_exit_code'] = code
    if result.get('command_exit_code')==1:
        smoke=offline_smoke_trace.sanitize(value.get('smoke_failure'))
        if smoke is not None:result['smoke_failure']=smoke
        if result['phase'] == 'import':
            imported = offline_import_trace.sanitize(value.get('import_failure'))
            if imported is not None:result['import_failure']=imported
    if result['phase'] in DEPLOY_FAILURE_PHASES and result.get('command_exit_code') == 1:
        deploy = sanitize_deploy_failure(value.get('deploy_failure'))
        if deploy is not None:
            result['deploy_failure'] = deploy
    if result['phase'] == 'https-data-check':
        https = sanitize_https_failure(value.get('https_failure'))
        if https is not None:
            result['https_failure'] = https
    if result['phase'] == 'rootless-database':
        database = sanitize_database_failure(value.get('database_failure'))
        if database is not None:
            result['database_failure'] = database
    command=value.get('guest_command')
    if isinstance(command,str) and command in GUEST_COMMANDS:
        result['guest_command']=command
        detail=value.get('guest_command_detail')
        result['guest_command_detail']=detail if isinstance(detail,str) and detail in GUEST_COMMAND_DETAILS else 'other'
    tool=value.get('host_tool')
    if isinstance(tool,str) and tool in HOST_TOOLS: result['host_tool']=tool
    detail=value.get('host_detail')
    if isinstance(detail,str) and detail in HOST_DETAILS: result['host_detail']=detail
    number=value.get('host_errno')
    if type(number) is int and 1<=number<=4095: result['host_errno']=number
    if result['phase'] == 'host-launch' and result['failure_type'] == 'HostLaunchError':
        reason = value.get('host_launch_reason')
        if isinstance(reason, str) and reason in HOST_LAUNCH_REASONS:
            result['host_launch_reason'] = reason
            guest_phase = value.get('guest_phase')
            if reason == 'vm-deadline' and isinstance(guest_phase, str) and guest_phase in FAILURE_PHASES - HOST_PHASES:
                result['guest_phase'] = guest_phase
                progress = value.get('reported_import_stage')
                if guest_phase == 'import' and isinstance(progress, str) and progress in IMPORT_STAGES:
                    result['reported_import_stage'] = progress
    if result['failure_type'] == 'JSONDecodeError':
        kind = value.get('json_input')
        if isinstance(kind, str) and kind in {'empty', 'object', 'array', 'other'}:
            result['json_input'] = kind
        for key in ('json_chars', 'json_position', 'json_line', 'json_column'):
            count = value.get(key)
            if type(count) is int and 0 <= count <= 10**7:
                result[key] = count
    if result['phase'] == 'network-audit' and result['failure_type'] == 'NetworkObservationError':
        observer = safe_failure_fields(value.get('observer'))
        if observer: result['observer'] = observer
    if result['phase'] == 'delivered-browser-workflows':
        browser = offline_host_evidence.sanitize_browser_failure(value.get('browser_failure'))
        if browser is not None:result['browser_failure']=browser
        browser_exit = value.get('browser_service_exit')
        if valid_service_exit(browser_exit):
            result['browser_service_exit'] = browser_exit
    if value.get('failure_source') == 'service-exit':
        result['failure_source']='service-exit'
    service_code=value.get('service_exit_code')
    if type(service_code) is int and 0<=service_code<=255:result['service_exit_code']=service_code
    if result.get('failure_source') == 'service-exit':
        if valid_service_exit(value.get('service_exit')):
            result['service_exit'] = value['service_exit']
        capture = value.get('kernel_exit_capture')
        if isinstance(capture, str) and capture in EXIT_TRACE_RESULTS:
            result['kernel_exit_capture'] = capture
        kernel_exit = value.get('kernel_exit')
        if isinstance(kernel_exit, dict):
            observed = {}
            for role in sorted(EXIT_ROLES):
                task = kernel_exit.get(role)
                if not isinstance(task, dict) or type(task.get('task_exited')) is not bool:
                    continue
                observed[role] = {'task_exited': task['task_exited']}
                code = task.get('requested_exit_code')
                if type(code) is int and 0 <= code <= 255:
                    observed[role]['requested_exit_code'] = code
            if observed:
                result['kernel_exit'] = observed
        errors = value.get('tracer_syscall_errors')
        if capture == 'observed' and isinstance(errors, list):
            result['tracer_syscall_errors'] = [
                {'call': row['call'], 'errno': row['errno'], 'age_ms': row['age_ms']}
                for row in errors[-4:]
                if isinstance(row, dict) and isinstance(row.get('call'), str)
                and row['call'] in TRACER_ERROR_CALLS
                and type(row.get('errno')) is int and 1 <= row['errno'] <= 4095
                and type(row.get('age_ms')) is int and 0 <= row['age_ms'] <= 2000
            ]
        stderr_bytes = value.get('installer_tracer_stderr_bytes')
        if type(stderr_bytes) is int and 0 <= stderr_bytes <= 0x7fffffff:
            result['installer_tracer_stderr_bytes'] = stderr_bytes
        import_stage = value.get('import_stage')
        if (capture == 'observed' and result['phase'] == 'import'
                and isinstance(import_stage, str) and import_stage in IMPORT_STAGES):
            result['import_stage'] = import_stage
    if result.get('failure_source') == 'service-exit' or result.get('host_launch_reason') == 'vm-deadline':
        operation = value.get('last_operation')
        if isinstance(operation, str) and re.fullmatch(r'(?:start|complete) [a-z-]+', operation):
            if operation.split()[1] in INSTALLER_OPERATIONS:
                result['last_operation'] = operation
    tracee_exit = value.get('tracee_exit')
    if isinstance(tracee_exit, dict):
        kind, status = tracee_exit.get('kind'), tracee_exit.get('status')
        if kind == 'exited' and type(status) is int and 0 <= status <= 255:
            result['tracee_exit'] = {'kind': 'exited', 'status': status}
        elif kind == 'killed' and isinstance(status, str) and status in SIGNALS:
            result['tracee_exit'] = {'kind': 'killed', 'status': status}
    size=value.get('tracee_stderr_bytes')
    if type(size) is int and 0<=size<=0x7fffffff:result['tracee_stderr_bytes']=size
    frames=value.get('guest_frames')
    if isinstance(frames,list):
        safe=[]
        for frame in frames[-16:]:
            if (isinstance(frame,dict) and isinstance(frame.get('file'),str)
                    and frame['file'] in FRAME_FILES and type(frame.get('line')) is int
                    and 1<=frame['line']<=100000):
                safe.append({'file':frame['file'],'line':frame['line']})
        if safe:result['guest_frames']=safe
    observers=value.get('observer_errors')
    if isinstance(observers,dict):
        safe={}
        for name in ('installer','manager'):
            flags=observers.get(name)
            if isinstance(flags,list):
                selected=sorted({f for f in flags if isinstance(f,str) and f in OBSERVER_FLAGS})
                if selected:safe[name]=selected
        if safe:result['observer_errors']=safe
    return result


def sanitize_database_failure(value):
    """Current service state and fixed journal patterns are diagnostics, not cause proof."""
    if not isinstance(value, dict):
        return None
    captures = {'observed', 'unavailable', 'invalid'}
    result = {key: value[key] if isinstance(value.get(key), str) and value[key] in captures else 'invalid'
              for key in ('state_capture', 'journal_capture')}
    scope=value.get('journal_scope')
    if isinstance(scope,str) and scope in {'guest-user','root-system-user-unit','root-synthetic-user'}:
        result['journal_scope']=scope
    reason=value.get('journal_failure')
    if isinstance(reason,str) and reason in {'command-exit','timeout','io-error'}:
        result['journal_failure']=reason
    code=value.get('journal_exit_code')
    if type(code) is int and 0<=code<=255:
        result['journal_exit_code']=code
    version=value.get('journal_podman_version')
    if (isinstance(version,list) and len(version)==3
            and all(type(part) is int and 0<=part<=999 for part in version)):
        result['journal_podman_version']=version
    if result['state_capture'] == 'observed':
        state = value.get('state')
        selected = {}
        if isinstance(state, dict):
            for key, allowed in offline_apply_trace.SERVICE_PROPERTIES.items():
                if isinstance(state.get(key), str) and state[key] in allowed:
                    selected[key] = state[key]
            for key, maximum in (('ExecMainCode', 3), ('ExecMainStatus', 255), ('NRestarts', 10**6)):
                number = state.get(key)
                if type(number) is int and 0 <= number <= maximum:
                    selected[key] = number
        if selected:
            result['state'] = selected
        else:
            result['state_capture'] = 'invalid'
    if result['journal_capture'] == 'observed':
        categories = value.get('categories')
        truncated = value.get('journal_tail_truncated')
        if (type(truncated) is bool and isinstance(categories, list)
                and len(categories) <= len(DATABASE_ERROR_PATTERNS)
                and all(isinstance(item, str) and item in DATABASE_ERROR_PATTERNS for item in categories)):
            result.update(categories=sorted(set(categories)), journal_tail_truncated=truncated)
        else:
            result['journal_capture'] = 'invalid'
    if scope=='root-synthetic-user' and result['journal_capture']=='observed':
        counts={key:value.get(key) for key in DATABASE_JOURNAL_COUNTS}
        sources=value.get('journal_sources')
        size=value.get('journal_bytes')
        unit_categories=value.get('journal_database_unit_categories')
        runtime_categories=value.get('journal_runtime_error_categories')
        if (all(type(number) is int and 0<=number<=40 for number in counts.values())
                and isinstance(sources,dict) and set(sources)==DATABASE_JOURNAL_SOURCES
                and all(type(number) is int and 0<=number<=40 for number in sources.values())
                and sum(sources.values())==counts['journal_records']
                and counts['journal_database_unit_records']<=counts['journal_records']
                and counts['journal_unclassified_error_records']<=counts['journal_runtime_error_records']<=counts['journal_records']
                and type(size) is int and 0<=size<=65536
                and all(isinstance(items,list) and len(items)<=len(DATABASE_ERROR_PATTERNS)
                        and all(isinstance(item,str) and item in DATABASE_ERROR_PATTERNS for item in items)
                        for items in (unit_categories,runtime_categories))
                and set(result.get('categories',[]))==set(unit_categories)|set(runtime_categories)):
            result.update(counts,journal_sources=sources,journal_bytes=size,
                journal_database_unit_categories=sorted(set(unit_categories)),
                journal_runtime_error_categories=sorted(set(runtime_categories)))
        else:
            result['journal_capture']='invalid'
            result.pop('categories',None)
            result.pop('journal_tail_truncated',None)
    return result


def database_journal_records(raw,truncated):
    """Count trusted UID matches; disclose only fixed components and pattern labels."""
    result={'state_capture':'unavailable','journal_capture':'invalid',
            'journal_scope':'root-synthetic-user'}
    if not isinstance(raw,bytes) or len(raw)>65536 or type(truncated) is not bool:
        return result
    sources=dict.fromkeys(DATABASE_JOURNAL_SOURCES,0)
    count=unit_count=error_count=unclassified=0
    categories=set();unit_categories=set();runtime_categories=set()
    try:
        for line in raw.splitlines():
            if not line.strip():continue
            record=json.loads(line)
            if (not isinstance(record,dict) or record.get('_UID')!='1001'
                    or not isinstance(record.get('MESSAGE'),str)):
                return result
            count+=1
            if count>40:return result
            command=record.get('_COMM')
            source=command if isinstance(command,str) and command in DATABASE_JOURNAL_SOURCES else 'other'
            sources[source]+=1
            unit=record.get('_SYSTEMD_USER_UNIT')=='sierx-postgres.service' or record.get('USER_UNIT')=='sierx-postgres.service'
            unit_count+=int(unit)
            message=record['MESSAGE'].encode('utf-8').lower()
            runtime_error=(source in DATABASE_RUNTIME_COMMANDS
                and (message.startswith(b'error:') or b'level=error' in message or message.startswith(b'fatal:')))
            if runtime_error:error_count+=1
            selected={key for key,pattern in DATABASE_ERROR_PATTERNS.items() if pattern in message} if unit or runtime_error else set()
            categories.update(selected)
            if unit:unit_categories.update(selected)
            if runtime_error:runtime_categories.update(selected)
            if runtime_error and not selected:unclassified+=1
    except (ValueError,UnicodeError):
        return result
    # A partial/lost journal window is diagnostic uncertainty, never evidence
    # that an error or record was absent.
    if truncated:return result
    result.update(journal_capture='observed',categories=sorted(categories),
                  journal_database_unit_categories=sorted(unit_categories),
                  journal_runtime_error_categories=sorted(runtime_categories),
                  journal_tail_truncated=False,journal_bytes=len(raw),journal_sources=sources,
                  journal_records=count,journal_database_unit_records=unit_count,
                  journal_runtime_error_records=error_count,journal_unclassified_error_records=unclassified)
    return sanitize_database_failure(result)


def database_podman_version():
    """Only the installed guest binary's numeric version, never command text."""
    try:
        with tempfile.TemporaryFile() as output:
            response=subprocess.run(('/usr/bin/podman','--version'),stdout=output,
                                    stderr=subprocess.DEVNULL,timeout=3)
            if response.returncode or output.tell()>256:return None
            output.seek(0)
            match=re.fullmatch(r'podman version ([0-9]{1,3})\.([0-9]{1,3})\.([0-9]{1,3})'
                r'(?:[-+~][A-Za-z0-9._~+-]{1,64})?\s*',output.read(256).decode('ascii'))
            return list(map(int,match.groups())) if match else None
    except (OSError,UnicodeError,subprocess.SubprocessError):
        return None


def checkpoint_database_journal(result,directory):
    """Root-only failed synthetic-user journal metadata before completion."""
    if not isinstance(result,dict) or result.get('result')!='failed' or result.get('phase')!='rootless-database':
        return None
    if os.geteuid()!=0:
        raise PermissionError('Database journal capture requires the guest root supervisor')
    directory=Path(directory)
    if directory.is_symlink() or not directory.is_dir() or directory.stat().st_mode & 0o077:
        raise ValueError('Database journal checkpoint requires protected guest storage')
    suite=(directory/'suite.sha256').read_text().strip()
    if not re.fullmatch('[a-f0-9]{64}',suite):
        raise ValueError('Missing database diagnostic suite identity')
    evidence={'state_capture':'unavailable','journal_capture':'unavailable',
              'journal_scope':'root-synthetic-user'}
    try:
        with tempfile.TemporaryFile() as output:
            # Volatile guest journals may omit user-unit matches. Keep this
            # broader UID-only context explicit; count exact DB unit records
            # separately and classify only those or fixed runtime error sources.
            response=subprocess.run(('journalctl','--no-pager','--all','--output=json',
                '_UID=1001','-n','40'),
                stdout=output,stderr=subprocess.DEVNULL,timeout=8)
            if response.returncode:
                evidence['journal_failure']='command-exit'
                if 0<=response.returncode<=255:
                    evidence['journal_exit_code']=response.returncode
            else:
                size=output.tell();output.seek(max(0,size-65536))
                evidence=database_journal_records(output.read(65536),size>65536)
    except subprocess.TimeoutExpired:
        evidence['journal_failure']='timeout'
    except (OSError,subprocess.SubprocessError):
        evidence['journal_failure']='io-error'
    version=database_podman_version()
    if version is not None:evidence['journal_podman_version']=version
    value={'schema':1,'suite':'offline-database-failure-v1','suite_sha256':suite,
           'result':'failed','phase':'rootless-database',
           'database_failure':sanitize_database_failure(evidence)}
    target=directory/'database-failure.json'
    if target.exists() or target.is_symlink():
        raise ValueError('Database checkpoint already exists')
    pending=directory/'database-failure.pending.json'
    fd=os.open(pending,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w') as output:
        json.dump(value,output);output.write('\n');output.flush();os.fsync(output.fileno())
    pending.replace(target)
    os.sync()
    return value


def merge_database_journal(result,checkpoint,suite):
    """Only a bound failed root checkpoint may enrich an already failed DB result."""
    if (not isinstance(result,dict) or result.get('result')!='failed'
            or result.get('phase')!='rootless-database' or not isinstance(checkpoint,dict)
            or set(checkpoint)!={'schema','suite','suite_sha256','result','phase','database_failure'}
            or type(checkpoint['schema']) is not int or checkpoint['schema']!=1
            or checkpoint['suite']!='offline-database-failure-v1'
            or not isinstance(suite,str) or not re.fullmatch('[a-f0-9]{64}',suite) or checkpoint['suite_sha256']!=suite
            or checkpoint['result']!='failed' or checkpoint['phase']!='rootless-database'):
        return result
    root=sanitize_database_failure(checkpoint['database_failure'])
    if root is None or root!=checkpoint['database_failure'] or root.get('journal_scope') not in {'root-system-user-unit','root-synthetic-user'}:
        return result
    current=sanitize_database_failure(result.get('database_failure')) or {
        'state_capture':'unavailable','journal_capture':'unavailable'}
    # Retain the guest's original current service state; this is journal metadata
    # only. A failed optional read cannot replace already observed journal data.
    if root['journal_capture']!='observed' and current['journal_capture']=='observed':
        return result
    for key in list(current):
        if key!='categories' and not key.startswith('journal_'):continue
        current.pop(key,None)
    current.update({key:value for key,value in root.items() if key.startswith('journal_') or key=='categories'})
    return {**result,'database_failure':sanitize_database_failure(current)}


def database_service_failure():
    """Read only the fixed database unit after the original failed checkpoint exists."""
    def bounded(args, limit):
        try:
            with tempfile.TemporaryFile() as output:
                response = subprocess.run(args, stdout=output, stderr=subprocess.DEVNULL, timeout=8)
                if response.returncode:
                    return None
                size = output.tell()
                output.seek(max(0, size-limit))
                return output.read(limit), size > limit
        except (OSError, subprocess.SubprocessError):
            return None

    result = {'state_capture':'unavailable', 'journal_capture':'unavailable'}
    properties = ('Id', *offline_apply_trace.SERVICE_PROPERTIES, 'ExecMainCode', 'ExecMainStatus', 'NRestarts')
    response = bounded(('systemctl','--user','show','--no-pager',
                        '--property='+','.join(properties),'sierx-postgres.service'), 8192)
    if response is not None:
        raw, truncated = response
        result['state_capture'] = 'invalid'
        try:
            rows = [line.split('=', 1) for line in raw.decode('ascii').splitlines() if line]
            if (not truncated and all(len(row)==2 for row in rows)
                    and len({row[0] for row in rows})==len(rows)):
                state = dict(rows)
                if state.pop('Id', None) == 'sierx-postgres.service':
                    for key in ('ExecMainCode','ExecMainStatus','NRestarts'):
                        number = state.get(key)
                        if isinstance(number, str) and number.isascii() and number.isdecimal():
                            state[key] = int(number) if len(number) <= 7 else -1
                    result.update(state_capture='observed', state=state)
        except UnicodeDecodeError:
            pass
    response = bounded(('journalctl','--user','--no-pager','--all','--output=cat',
                        '-u','sierx-postgres.service','-n','40'), 65536)
    if response is not None:
        raw, truncated = response
        result.update(journal_capture='observed', journal_tail_truncated=truncated,
                      categories=sorted(key for key, pattern in DATABASE_ERROR_PATTERNS.items()
                                        if pattern in raw.lower()))
    return sanitize_database_failure(result)


def guest_command_failure(args, stderr):
    """Classify only fixed Podman operations/errors; never expose argv/stderr."""
    if len(args)<2 or str(args[0])!='podman':
        return {}
    operation = str(args[1])
    if tuple(map(str, args[:3])) == ('podman', 'image', 'inspect'):
        operation = 'inspect'
    if operation not in {'info','inspect','pull'}:
        return {}
    text=stderr.lower() if isinstance(stderr,bytes) else b''
    patterns=((b'database configuration mismatch','storage-configuration'),
              (b'database is locked','database-lock'),(b'permission denied','permission-denied'),
              (b'no space left on device','storage-full'),
              (b'resource temporarily unavailable','resource-unavailable'),
              (b'cannot clone','namespace-clone'),(b'cannot re-exec','reexec'),
              (b'context deadline exceeded','deadline'),(b'unexpected eof','unexpected-eof'),
              (b'x509:','tls-verification'),(b'connection refused','connection-refused'),
              (b'manifest unknown','manifest-unknown'))
    detail=next((label for message,label in patterns if message in text),'other')
    return {'guest_command':'podman-'+operation,'guest_command_detail':detail}


def sanitize_deploy_failure(record):
    if not isinstance(record, dict):
        return None
    terminal = offline_apply_trace.sanitize_exception(record.get('terminal'))
    if terminal is None:
        return None
    result = {'terminal': terminal}
    context = offline_apply_trace.sanitize_exception(record.get('context'))
    if context is not None:
        result['context'] = context
    return result


def deploy_stderr_failure(stderr):
    prefix = offline_apply_trace.MARKER.encode('ascii')
    markers = [line.removeprefix(prefix) for line in stderr.splitlines() if line.startswith(prefix)]
    if len(markers) != 1 or len(markers[0]) > 1024:
        return None
    try:
        return sanitize_deploy_failure(json.loads(markers[0]))
    except (ValueError, UnicodeError):
        return None


def sanitize_https_failure(value):
    if not isinstance(value, dict):
        return None
    step, kind = value.get('step'), value.get('kind')
    if not isinstance(step, str) or step not in HTTPS_STEPS:
        return None
    if not isinstance(kind, str) or kind not in HTTPS_FAILURE_KINDS:
        return None
    result = {'step': step, 'kind': kind}
    if kind == 'http-status':
        status = value.get('http_status')
        if type(status) is not int or not 100 <= status <= 599:
            return None
        result['http_status'] = status
    else:
        number = value.get('errno')
        if type(number) is int and 1 <= number <= 4095:
            result['errno'] = number
    io=value.get('io_stage')
    if isinstance(io,str) and io in offline_smoke_trace.IO_STAGES:result['io_stage']=io
    activity=offline_smoke_trace.sanitize_activity(value.get('activity'))
    if activity is not None:result['activity']=activity
    return result


def sanitize_preparation_failure(value):
    if not isinstance(value, dict):
        return None
    stage, status = value.get('stage'), value.get('exit_code')
    if (not isinstance(stage, str) or stage not in PREPARATION_STAGES
            or type(status) is not int or not 1 <= status <= 255):
        return None
    result = {'stage': stage, 'exit_code': status}
    build = value.get('last_build_stage')
    if stage == 'build-os' and isinstance(build, str) and build in BUILD_STAGES:
        result['last_build_stage'] = build
    return result


def preparation_failure(stage, status, build_log):
    value = {'stage': stage, 'exit_code': status}
    if stage == 'build-os' and build_log is not None:
        prefix = 'SIERX_HOST_BUILD_STAGE: '
        for line in build_log:
            if line.startswith(prefix):
                label = line.removeprefix(prefix).rstrip('\r\n')
                if label in BUILD_STAGES:
                    value['last_build_stage'] = label
    return sanitize_preparation_failure(value)


def classify_https_failure(error, step, activity=None):
    if isinstance(error, urllib.error.HTTPError):
        value={'step': step, 'kind': 'http-status', 'http_status': error.code}
    else:
        reason = error.reason if isinstance(error, urllib.error.URLError) else error
        kind = next((label for subtype, label in HTTPS_TRANSPORT_ERRORS if isinstance(reason, subtype)), None)
        if kind is None and isinstance(error, urllib.error.URLError):
            kind = 'url-error'
        value={'step': step, 'kind': kind, 'errno': getattr(reason, 'errno', None)}
        io=offline_smoke_trace.io_stage(error,error.__traceback__)
        if io!='unknown':value['io_stage']=io
    if activity is not None:
        value['activity']=offline_smoke_trace.activity_summary(activity,offline_smoke_trace.activity_snapshot())
    return sanitize_https_failure(value)


def failure_record(error, phase):
    suite_dir = Path(__file__).parent
    frames = []
    for frame, line in traceback.walk_tb(error.__traceback__):
        source = Path(frame.f_code.co_filename)
        if source.parent == suite_dir and source.name in FRAME_FILES:
            frames.append({'file': source.name, 'line': line})
    value = {'result':'failed', 'phase':phase, 'failure_type':type(error).__name__,
             'guest_frames':frames,
             'host_launch_reason':getattr(error, 'host_launch_reason', None),
             'guest_phase':getattr(error, 'guest_phase', None),
             'last_operation':getattr(error, 'last_operation', None),
             'reported_import_stage':getattr(error, 'reported_import_stage', None),
             'command_exit_code':getattr(error, 'fixture_exit_code', None),
             'deploy_failure':getattr(error, 'deploy_failure', None),
             'smoke_failure':getattr(error, 'smoke_failure', None),
             'import_failure':getattr(error, 'import_failure', None),
             'https_failure':getattr(error, 'https_failure', None),
             'observer':getattr(error, 'observer_details', None),
             'host_tool':getattr(error,'host_tool',None),'host_errno':getattr(error,'errno',None),
             'host_detail':getattr(error,'host_detail',None),
             'browser_service_exit':getattr(error,'browser_service_exit',None),
             'browser_failure':getattr(error,'browser_failure',None),
             'guest_command':getattr(error,'fixture_command',None),
             'guest_command_detail':getattr(error,'fixture_command_detail',None)}
    if isinstance(error, json.JSONDecodeError):
        first = error.doc.lstrip()[:1]
        value.update(json_input='empty' if not first else 'object' if first=='{' else 'array' if first=='[' else 'other',
                     json_chars=len(error.doc), json_position=error.pos,
                     json_line=error.lineno, json_column=error.colno)
    return sanitize_failure(value)


def checkpoint_failure(home, value):
    """Sync a failed-only diagnostic before optional journal collection can fail."""
    failure = sanitize_failure(value)
    pending = Path(home)/'failure.pending.json'
    pending.write_text(json.dumps(failure)+'\n')
    pending.replace(Path(home)/'failure.json')
    os.sync()
    print('SIERX_FAILURE: '+json.dumps(failure, sort_keys=True), flush=True)
    return failure


def journal_failure(text):
    """Keep fixed source names/line numbers and exception classes, never messages."""
    value={}
    for name in re.findall(r'^([A-Za-z]+):',text,re.MULTILINE):
        if name in FAILURE_TYPES:value['failure_type']=name
    frames=[]
    for name,line in re.findall(r'^  File "/opt/acceptance/tests/([A-Za-z_-]+\.py)", line ([0-9]{1,6}),',text,re.MULTILINE):
        if name in FRAME_FILES and 1<=int(line)<=100000:
            frames.append({'file':name,'line':int(line)})
    if frames:value['guest_frames']=frames[-16:]
    return value


def observer_errors(text):
    """Fixed categories observed in strace stderr; not a root-cause assertion."""
    flags=set()
    patterns=(('ptrace','ptrace'),('seccomp','seccomp'),('wait','wait'),
              ('input/output error','io-error'),('permission denied','permission-denied'),
              ('operation not permitted','permission-denied'),('no child processes','no-child'),
              ('unexpected wait','unexpected-wait'))
    for line in text.splitlines():
        message = re.fullmatch(r'(?:strace|/usr/bin/strace): (.*)', line)
        if not message:continue
        if re.fullmatch(r'Process [0-9]+ (?:attached|detached)',message[1]):continue
        selected={flag for pattern,flag in patterns if pattern in message[1].lower()}
        flags.update(selected or {'other-error'})
    return sorted(flags)


def private_tail(path,limit=65536):
    try:
        with Path(path).open('rb') as stream:
            stream.seek(0,os.SEEK_END)
            stream.seek(max(0,stream.tell()-limit))
            return stream.read(limit).decode(errors='replace')
    except OSError:
        return ''


def installer_exit(path):
    """Read the terminal record for the initial installer, ignoring children."""
    header = rb'(?:<[^>\r\n]+>)?[ \t]+[0-9]+\.[0-9]+[ \t]+'
    try:
        with Path(path).open('rb') as stream:
            start = re.fullmatch(rb'([0-9]+)' + header +
                rb'execve\("/usr/sbin/sierx-observed-installer", .*\) += 0\n', stream.readline(4096))
            if not start:
                return None
            terminal = re.compile(start[1] + header +
                rb'\+\+\+ (?:exited with ([0-9]{1,3})|killed by SIG([A-Z0-9]+)(?: \(core dumped\))?) \+\+\+\n')
            # Start at the original exec so a later reuse of its PID cannot
            # supersede a terminal status already recorded for this process.
            for line in stream:
                if not line.startswith(start[1]):
                    continue
                match = terminal.fullmatch(line)
                if match:
                    if match[1] is not None and int(match[1]) <= 255:
                        return {'kind': 'exited', 'status': int(match[1])}
                    if match[2] is not None and match[2].decode('ascii') in SIGNALS:
                        return {'kind': 'killed', 'status': match[2].decode('ascii')}
                    return None
    except OSError:
        pass
    return None


def start_installer_exit_trace(instance=INSTALLER_EXIT_TRACE):
    """Use a separate, bounded kernel trace for the stress diagnostic only."""
    instance.mkdir()
    (instance / 'tracing_on').write_text('0')
    (instance / 'trace_clock').write_text('mono')
    (instance / 'trace').write_text('')
    for event in ('syscalls/sys_enter_exit_group', 'sched/sched_process_exit'):
        (instance / 'events' / event / 'enable').write_text('1')
    (instance / 'tracing_on').write_text('1')


def enable_tracer_error_events(instance=INSTALLER_EXIT_TRACE):
    """Filter in the kernel to negative returns from the already marked tracer."""
    with (instance / 'trace').open(encoding='ascii', errors='replace') as trace:
        starts = [match[1] for line in trace.read(65536).splitlines()
                  if (match := EXIT_TRACE_LINE.fullmatch(line))
                  and match[3] == 'tracing_mark_write: sierx-tracer-start']
    if len(starts) != 1 or not 0 < int(starts[0]) <= 0x7fffffff:
        raise ValueError('Independent trace did not identify one installer tracer')
    for call in sorted(TRACER_ERROR_CALLS):
        event = instance / 'events' / 'syscalls' / ('sys_exit_' + call)
        (event / 'filter').write_text('common_pid == ' + starts[0] + ' && ret < 0')
        (event / 'enable').write_text('1')


def mark_installer(message):
    os.write(INSTALLER_MARKER_FD, (message + '\n').encode('ascii'))


def observe_import(path, emit=mark_installer):
    """Run the verified bundle helper unchanged, reporting only fixed stage entries."""
    next_stage = iter(IMPORT_STAGES)

    def stage(name):
        if name != next(next_stage, None):
            raise ValueError('Unexpected historical import stage')
        emit('sierx-import-stage ' + name)

    def observe(frame, event, _result):
        if event != 'call' or frame.f_code.co_filename != path:
            return
        name = frame.f_code.co_name
        if name == 'verify':
            stage('verify-bundle')
            return
        parent = frame.f_back
        if (parent is None or parent.f_code.co_filename != path
                or parent.f_code.co_name != 'run_operation'):
            return
        role = parent.f_locals.get('role')
        if role not in IMPORT_ROLES:
            return
        if name == 'command' and frame.f_locals['args'][:2] == ('podman', 'load'):
            stage('load-' + role)
        elif name == 'inspect_image':
            stage('inspect-' + role)

    argv = sys.argv
    profile = sys.getprofile()
    sys.argv = [path, 'import']
    sys.setprofile(observe)
    try:
        runpy.run_path(path, run_name='__main__')
    finally:
        sys.setprofile(profile)
        sys.argv = argv
    stage('import-complete')


def installer_exit_events(lines):
    """Bind events to the two kernel-attributed start markers, without exporting PIDs."""
    entries = None
    records = 0
    roles = {}
    observed = {}
    phase = operation = None
    import_pid = None
    import_stages = []
    tracer_errors = deque(maxlen=4)
    tracer_errors_ready = False
    tracer_exit_at = None
    for line in lines:
        match = EXIT_TRACE_LINE.match(line.rstrip('\n'))
        if not match:
            if line.startswith('#') and records == 0:
                header = re.match(r'# entries-in-buffer/entries-written:\s+(\d+)/(\d+)', line)
                if header:
                    if header[1] != header[2] or not 0 < int(header[1]) <= 250000:
                        return {}
                    entries = int(header[1])
                continue
            return {}
        records += 1
        if entries is None or records > entries:
            return {}
        pid, timestamp, event = match.groups()
        if event.startswith('tracing_mark_write: sierx-import-stage '):
            stage = event.removeprefix('tracing_mark_write: sierx-import-stage ')
            if (phase != 'import' or operation != 'start import'
                    or any(observed.get(role, {}).get('task_exited', True) for role in ('installer', 'tracer'))
                    or (import_pid is None and pid in roles)
                    or (import_pid is not None and (pid != import_pid or observed['import-helper']['task_exited']))
                    or tuple(import_stages + [stage]) != IMPORT_STAGES[:len(import_stages) + 1]):
                return {}
            if import_pid is None:
                import_pid = pid
                roles[pid] = 'import-helper'
                observed['import-helper'] = {'task_exited': False}
            import_stages.append(stage)
            continue
        start = re.fullmatch(r'tracing_mark_write: sierx-(tracer|installer)-start', event)
        if start:
            role = start[1]
            if pid in roles or role in observed:
                return {}
            roles[pid] = role
            observed[role] = {'task_exited': False}
            continue
        role = roles.get(pid)
        if role is None:
            continue
        task = observed[role]
        exit_request = re.fullmatch(r'sys_exit_group\(error_code: ((?:0x)?[0-9a-f]+)\)', event)
        if exit_request:
            if task['task_exited'] or 'requested_exit_code' in task:
                return {}
            task['requested_exit_code'] = int(exit_request[1], 16) & 255
            if role == 'tracer':
                tracer_exit_at = float(timestamp)
        elif event.startswith('sched_process_exit:'):
            exit_event = SCHED_PROCESS_EXIT.fullmatch(event)
            if not exit_event or task['task_exited'] or exit_event[1] != pid:
                return {}
            task['task_exited'] = True
            if role == 'tracer' and tracer_exit_at is None:
                tracer_exit_at = float(timestamp)
        elif role == 'tracer' and tracer_exit_at is None:
            if event == 'tracing_mark_write: sierx-tracer-errors-ready':
                tracer_errors_ready = True
            elif tracer_errors_ready and (returned := TRACER_RETURN.fullmatch(event)):
                code = int(returned[2], 10 if returned[2].startswith('-') else 16)
                if 2**63 <= code < 2**64:
                    code -= 2**64
                if -4095 <= code < 0:
                    tracer_errors.append((float(timestamp), returned[1], -code))
        elif role == 'installer' and not task['task_exited']:
            if event.startswith('tracing_mark_write: sierx-phase '):
                phase = event.removeprefix('tracing_mark_write: sierx-phase ')
                operation = None
            elif event.startswith('tracing_mark_write: sierx-operation '):
                operation = event.removeprefix('tracing_mark_write: sierx-operation ')
    if records != entries:
        return {}
    result = {'kernel_exit': observed, 'operation_phase': phase, 'last_operation': operation}
    if import_stages and phase == 'import':
        result['import_stage'] = import_stages[-1]
    if tracer_errors_ready and tracer_exit_at is not None and observed['tracer']['task_exited']:
        result['tracer_syscall_errors'] = [
            {'call': call, 'errno': number, 'age_ms': round((tracer_exit_at - at) * 1000)}
            for at, call, number in tracer_errors if 0 <= tracer_exit_at - at <= 2
        ]
    return result


def read_installer_exit_trace(instance):
    try:
        (instance / 'tracing_on').write_text('0')
    except FileNotFoundError:
        return {}
    except OSError:
        return {'kernel_exit_capture': 'unavailable'}
    try:
        for cpu in (instance / 'per_cpu').iterdir():
            losses = {}
            for line in (cpu / 'stats').read_text().splitlines():
                key, _, count = line.partition(':')
                if key.strip() in {'overrun', 'commit overrun', 'dropped events'}:
                    losses[key.strip()] = int(count)
            if len(losses) != 3:
                return {'kernel_exit_capture': 'invalid-records'}
            if any(losses.values()):
                return {'kernel_exit_capture': 'lost-events'}
        with (instance / 'trace').open(encoding='ascii', errors='replace') as trace:
            evidence = installer_exit_events(trace)
        return {'kernel_exit_capture': 'observed' if evidence.get('kernel_exit') else 'invalid-records',
                **evidence}
    except OSError:
        return {'kernel_exit_capture': 'unavailable'}
    except ValueError:
        return {'kernel_exit_capture': 'invalid-records'}


def checkpoint_service_failure(home,directory,environment=None,exit_trace=INSTALLER_EXIT_TRACE):
    """Independent root hook survives installer/observer death and missing result."""
    status=service_exit(environment)
    if status=={'service_result':'success','exit_kind':'exited','exit_status':0}:return None
    value={'result':'failed','phase':'unknown','failure_type':'ServiceExit',
           'failure_source':'service-exit','service_exit_code':status['exit_status'],
           'service_exit':status}
    try:
        progress=json.loads(private_tail(Path(home)/'progress.json',4096))
        if isinstance(progress,dict):value['phase']=progress.get('phase')
    except ValueError:
        pass
    try:
        journal=subprocess.run(['journalctl','--no-pager','--all','--output=cat',
            '-u','sierx-acceptance.service','-n','100'],stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,timeout=15)
        if journal.returncode==0:value.update(journal_failure(journal.stdout[-65536:].decode(errors='replace')))
    except (OSError,subprocess.SubprocessError):
        pass
    # This root-opened descriptor is independent of journal delivery/rate
    # limits. Publish only fixed exception classes/public source locations.
    direct=Path(directory)/'installer-guest.stderr'
    try:
        value['tracee_stderr_bytes']=direct.stat().st_size
        value.update(journal_failure(private_tail(direct)))
    except OSError:
        pass
    value['tracee_exit'] = installer_exit(Path(directory) / 'installer.trace')
    exit_evidence = read_installer_exit_trace(exit_trace)
    value['kernel_exit_capture'] = exit_evidence.get('kernel_exit_capture')
    value['kernel_exit'] = exit_evidence.get('kernel_exit')
    value['tracer_syscall_errors'] = exit_evidence.get('tracer_syscall_errors')
    try:
        value['installer_tracer_stderr_bytes'] = (Path(directory) / 'installer.stderr').stat().st_size
    except OSError:
        pass
    if exit_evidence.get('operation_phase') == value['phase']:
        value['last_operation'] = exit_evidence.get('last_operation')
        value['import_stage'] = exit_evidence.get('import_stage')
    value['observer_errors']={name:observer_errors(private_tail(Path(directory)/(name+'.stderr')))
                              for name in ('installer','manager')}
    failure=sanitize_failure(value)
    pending=Path(directory)/'service-failure.pending.json'
    pending.write_text(json.dumps(failure)+'\n')
    pending.chmod(0o600)
    pending.replace(Path(directory)/'service-failure.json')
    os.sync()
    print('SIERX_FAILURE: '+json.dumps(failure,sort_keys=True),flush=True)
    return failure


def resources(root=Path('/')):
    result = dict.fromkeys(RESOURCE_KEYS)
    try:
        storage = os.statvfs(root)
        result['disk_available_bytes'] = storage.f_bavail * storage.f_frsize
    except OSError:
        pass
    for name, pattern, key, factor in (
        ('meminfo', r'^MemAvailable:\s+(\d+) kB$', 'memory_available_bytes', 1024),
        ('vmstat', r'^oom_kill (\d+)$', 'oom_kills', 1),
    ):
        try:
            match = re.search(pattern, (root/'proc'/name).read_text(), re.MULTILINE)
            if match:
                result[key] = int(match[1]) * factor
        except OSError:
            pass
    for name in ('manager', 'installer'):
        try:
            result[name+'_trace_bytes'] = (root/'var/log/sierx-network'/(name+'.trace')).stat().st_size
        except OSError:
            pass
    return result


def service_exit(environment=None):
    environment = os.environ if environment is None else environment
    result = environment.get('SERVICE_RESULT', 'unknown')
    kind = environment.get('EXIT_CODE', 'unknown')
    status = environment.get('EXIT_STATUS', 'unknown')
    if status.isascii() and status.isdecimal() and len(status) <= 3 and int(status) <= 255:
        status = int(status)
    elif status not in SIGNALS:
        status = 'unknown'
    return {'service_result': result if result in SERVICE_RESULTS else 'unknown',
            'exit_kind': kind if kind in EXIT_KINDS else 'unknown', 'exit_status': status}


def valid_service_exit(value):
    return (isinstance(value, dict) and set(value) == {'service_result', 'exit_kind', 'exit_status'}
            and isinstance(value['service_result'], str) and value['service_result'] in SERVICE_RESULTS
            and isinstance(value['exit_kind'], str) and value['exit_kind'] in EXIT_KINDS
            and (type(value['exit_status']) is int and 0 <= value['exit_status'] <= 255
                 or isinstance(value['exit_status'], str) and value['exit_status'] in SIGNALS | {'unknown'}))


def write_browser_exit(path):
    """Save the browser unit's main process status before systemd collects it."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as output:
        json.dump(service_exit(), output)


def read_browser_exit(path):
    try:
        value = json.loads(private_tail(path, 4096))
    except ValueError:
        return None
    return value if valid_service_exit(value) else None


def emit_resources():
    print('SIERX_RESOURCES: '+json.dumps(resources(), sort_keys=True), flush=True)


def latest(console, marker):
    for value in reversed(re.findall(re.escape(marker)+r': (\{[^\r\n]{1,1024}\})', console)):
        try:
            data = json.loads(value)
        except (ValueError, TypeError):
            continue
        if marker == 'SIERX_RESOURCES':
            if (isinstance(data, dict) and set(data) == RESOURCE_KEYS
                    and all(v is None or type(v) is int and 0 <= v < 2**63 for v in data.values())):
                return data
        elif marker == 'SIERX_GUEST_EXIT':
            if valid_service_exit(data):
                return data
        elif marker == 'SIERX_FAILURE':
            if isinstance(data,dict) and data.get('result')=='failed':
                return sanitize_failure(data)
    return None


def stopped(returncode, console, emulator_output, host_before=None):
    return {'qemu_exit_code': returncode if type(returncode) is int and -128 <= returncode <= 255 else None,
            'guest_exit': latest(console, 'SIERX_GUEST_EXIT'),
            'resources': latest(console, 'SIERX_RESOURCES'),
            'host_resources_before': host_before,
            'host_resources_after': resources(),
            'oom_message_observed': bool(re.search(r'Out of memory:|oom-kill:|Memory cgroup out of memory:', console)),
            'storage_error_observed': 'No space left on device' in console or 'No space left on device' in emulator_output,
            'emulator_allocation_error_observed': 'Cannot allocate memory' in emulator_output,
            'emulator_assertion_observed': bool(re.search(r'assertion .*failed|Assertion .*failed', emulator_output))}


def reported_import_stage(console):
    """Only a complete ordered console prefix identifies the last reported entry."""
    stages = tuple(re.findall(r'(?:^| )SIERX_IMPORT_STAGE: ([^\r\n]*)\r?\n', console, re.MULTILINE))
    if stages and stages == IMPORT_STAGES[:len(stages)]:
        return stages[-1]
    return None


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--observe-import' and os.geteuid() == 1001:
        progress = int(sys.argv[2])
        os.set_inheritable(INSTALLER_MARKER_FD, False)
        os.set_inheritable(progress, False)

        def emit_import_progress(marker):
            mark_installer(marker)
            stage = marker.removeprefix('sierx-import-stage ')
            os.write(progress, ('SIERX_IMPORT_STAGE: ' + stage + '\n').encode('ascii'))

        observe_import('/opt/sierx-bundle/scripts/offline.py', emit_import_progress)
        sys.exit(0)
    if len(sys.argv) == 3 and sys.argv[1] == '--browser-exit':
        write_browser_exit(Path(sys.argv[2]))
        sys.exit(0)
    if sys.argv[1:] == ['--start-installer-exit-trace'] and os.geteuid() == 0:
        start_installer_exit_trace()
        sys.exit(0)
    if sys.argv[1:] == ['--enable-tracer-error-events'] and os.geteuid() == 0:
        enable_tracer_error_events()
        sys.exit(0)
    if sys.argv[1:] != ['--service-exit']:
        raise SystemExit('Unsupported diagnostic operation')
    emit_resources()
    print('SIERX_GUEST_EXIT: '+json.dumps(service_exit(), sort_keys=True), flush=True)
    if os.geteuid()!=0:raise SystemExit('Service-exit observation requires the guest root unit')
    checkpoint_service_failure(Path('/home/acceptance'),Path('/var/log/sierx-network'))
