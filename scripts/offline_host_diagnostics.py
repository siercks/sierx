"""Allowlisted VM failure metadata; never a passing acceptance report."""
import json
import os
from pathlib import Path
import re
import signal
import sys

RESOURCE_KEYS = {'disk_available_bytes', 'memory_available_bytes', 'oom_kills',
                 'manager_trace_bytes', 'installer_trace_bytes'}
SERVICE_RESULTS = {'success', 'resources', 'timeout', 'exit-code', 'signal',
                   'core-dump', 'watchdog', 'start-limit-hit', 'oom-kill',
                   'exec-condition', 'protocol', 'unknown'}
EXIT_KINDS = {'exited', 'killed', 'dumped', 'unknown'}
SIGNALS = {entry.name.removeprefix('SIG') for entry in signal.Signals}
FAILURE_TYPES = {'TimeoutExpired', 'ValueError', 'RuntimeError', 'PermissionError',
                 'FileNotFoundError', 'JSONDecodeError', 'UnicodeDecodeError',
                 'TypeError', 'KeyError', 'AttributeError', 'AssertionError', 'OSError'}
FAILURE_PHASES = {'initialization', 'import', 'rootless-database', 'migration-bootstrap',
                  'actual-plan-apply', 'https-data-check', 'repeat-apply', 'restart',
                  'network-negative-controls', 'negative-app', 'negative-gateway',
                  'negative-database', 'negative-installer', 'negative-dns-ipv-six',
                  'delivered-browser-workflows', 'invalid-deliveries', 'two-approved-releases',
                  'failed-health-rollback', 'bounded-runtime', 'explicit-opt-in-acquisition', 'complete',
                  'network-audit'} | {
    'runtime-'+name for name in ('reject-implicit-timers', 'reload-units', 'start-timer',
                                'observe', 'verify-maintenance', 'inventory-services',
                                'inventory-timers', 'inventory-enabled')}


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
    if result['failure_type'] == 'JSONDecodeError':
        kind = value.get('json_input')
        if isinstance(kind, str) and kind in {'empty', 'object', 'array', 'other'}:
            result['json_input'] = kind
        for key in ('json_chars', 'json_position', 'json_line', 'json_column'):
            count = value.get(key)
            if type(count) is int and 0 <= count <= 10**7:
                result[key] = count
    return result


def failure_record(error, phase):
    value = {'result':'failed', 'phase':phase, 'failure_type':type(error).__name__,
             'command_exit_code':getattr(error, 'fixture_exit_code', None)}
    if isinstance(error, json.JSONDecodeError):
        first = error.doc.lstrip()[:1]
        value.update(json_input='empty' if not first else 'object' if first=='{' else 'array' if first=='[' else 'other',
                     json_chars=len(error.doc), json_position=error.pos,
                     json_line=error.lineno, json_column=error.colno)
    return sanitize_failure(value)


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
            if (isinstance(data, dict) and set(data) == {'service_result', 'exit_kind', 'exit_status'}
                    and isinstance(data['service_result'], str) and data['service_result'] in SERVICE_RESULTS
                    and isinstance(data['exit_kind'], str) and data['exit_kind'] in EXIT_KINDS
                    and (type(data['exit_status']) is int and 0 <= data['exit_status'] <= 255
                         or isinstance(data['exit_status'], str) and data['exit_status'] in SIGNALS | {'unknown'})):
                return data
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


if __name__ == '__main__':
    if sys.argv[1:] != ['--service-exit']:
        raise SystemExit('Unsupported diagnostic operation')
    emit_resources()
    print('SIERX_GUEST_EXIT: '+json.dumps(service_exit(), sort_keys=True), flush=True)
