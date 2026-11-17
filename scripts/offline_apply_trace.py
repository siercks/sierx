"""Capture fixed exception evidence from the unmodified historical deploy helper."""
import json
import os
import subprocess
import sys

MARKER = 'SIERX_DEPLOY_FAILURE: '
ERRORS = {'BlockingIOError', 'CalledProcessError', 'FileNotFoundError', 'HTTPError',
          'JSONDecodeError', 'OSError', 'PermissionError', 'TimeoutError', 'URLError', 'ValueError'}
COMMANDS = {
    ('podman', 'image', 'inspect'): 'inspect-image',
    ('podman', 'create'): 'create-container',
    ('podman', 'cp'): 'copy-assets',
    ('podman', 'rm'): 'remove-container',
    ('systemctl', '--user', 'daemon-reload'): 'reload-services',
    ('systemctl', '--user', 'restart'): 'restart-services',
    ('systemctl', '--user', 'stop'): 'stop-services',
}
SERVICE_UNITS = {'sierx.service': 'app', 'sierx-caddy.service': 'gateway'}
SERVICE_PROPERTIES = {
    'LoadState': {'loaded', 'not-found', 'error', 'bad-setting', 'masked'},
    'ActiveState': {'active', 'inactive', 'failed', 'activating', 'deactivating', 'reloading', 'maintenance'},
    'SubState': {'running', 'exited', 'dead', 'failed', 'start-pre', 'start', 'start-post',
                 'stop', 'stop-sigterm', 'stop-sigkill', 'stop-post', 'final-sigterm',
                 'final-sigkill', 'auto-restart', 'auto-restart-queued', 'condition'},
    'Result': {'success', 'resources', 'protocol', 'timeout', 'exit-code', 'signal',
               'core-dump', 'watchdog', 'start-limit-hit', 'oom-kill', 'exec-condition', 'skipped'},
}
JOB_REASONS = {
    'failed because a timeout was exceeded.': 'timeout',
    'failed because the control process exited with error code.': 'control-exit',
    'failed because the service did not take the steps required by its unit configuration.': 'protocol',
    'failed because of unavailable resources or another system error.': 'resources',
}


def sanitize_service_states(value):
    if not isinstance(value, dict):
        return {}
    safe = {}
    for role in SERVICE_UNITS.values():
        properties = value.get(role)
        if not isinstance(properties, dict):
            continue
        selected = {key: item for key, item in properties.items()
                    if key in SERVICE_PROPERTIES and isinstance(item, str) and item in SERVICE_PROPERTIES[key]}
        for key, maximum in (('ExecMainCode', 3), ('ExecMainStatus', 255)):
            item = properties.get(key)
            if type(item) is int and 0 <= item <= maximum:
                selected[key] = item
        if selected:
            safe[role] = selected
    return safe


def capture_service_states():
    properties = ('Id', *SERVICE_PROPERTIES, 'ExecMainCode', 'ExecMainStatus')
    try:
        response = subprocess.run(('systemctl', '--user', 'show', '--no-pager',
            '--property=' + ','.join(properties), *SERVICE_UNITS),
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=8)
        if response.returncode or len(response.stdout) > 8192:
            return {}
        units = {}
        for block in response.stdout.decode('ascii', errors='replace').strip().split('\n\n'):
            values = dict(line.split('=', 1) for line in block.splitlines() if '=' in line)
            role = SERVICE_UNITS.get(values.get('Id'))
            if role is None or role in units:
                return {}
            for field in ('ExecMainCode', 'ExecMainStatus'):
                if values.get(field, '').isascii() and values[field].isdecimal():
                    values[field] = int(values[field])
            units[role] = values
        return sanitize_service_states(units)
    except (OSError, ValueError, subprocess.SubprocessError):
        return {}


def job_failures(stderr):
    if not isinstance(stderr, (bytes, str)):
        return {}
    text = stderr.decode(errors='replace') if isinstance(stderr, bytes) else stderr
    return {role: reason for unit, role in SERVICE_UNITS.items() for suffix, reason in JOB_REASONS.items()
            if 'Job for ' + unit + ' ' + suffix in text}


def sanitize_exception(record):
    if not isinstance(record, dict) or not isinstance(record.get('kind'), str) or record['kind'] not in ERRORS:
        return None
    lines = record.get('lines')
    if not isinstance(lines, list) or not 1 <= len(lines) <= 8 or any(
            type(line) is not int or not 1 <= line <= 100000 for line in lines):
        return None
    result = {'kind': record['kind'], 'lines': lines}
    command = record.get('command')
    if isinstance(command, str) and command in COMMANDS.values():
        result['command'] = command
    for field, lower, upper in (('errno', 1, 4095), ('exit_code', -127, 255), ('http_status', 100, 599)):
        value = record.get(field)
        if type(value) is int and lower <= value <= upper:
            result[field] = value
    states = sanitize_service_states(record.get('service_states'))
    if states:
        result['service_states'] = states
    jobs = record.get('service_job_failures')
    if isinstance(jobs, dict):
        selected = {role: reason for role, reason in jobs.items()
                    if role in SERVICE_UNITS.values() and isinstance(reason, str) and reason in JOB_REASONS.values()}
        if selected:
            result['service_job_failures'] = selected
    return result


def summarize_exception(error, traceback, source):
    lines = []
    while traceback is not None:
        if traceback.tb_frame.f_code.co_filename == source:
            lines.append(traceback.tb_lineno)
        traceback = traceback.tb_next
    record = {'kind': type(error).__name__, 'lines': lines[-8:]}
    reason = getattr(error, 'reason', None)
    record['errno'] = getattr(error, 'errno', None) or getattr(reason, 'errno', None)
    record['http_status'] = getattr(error, 'code', None)
    if isinstance(error, subprocess.CalledProcessError) and isinstance(error.cmd, (tuple, list)):
        for prefix, command in COMMANDS.items():
            if tuple(error.cmd[:len(prefix)]) == prefix:
                record['command'] = command
                break
        record['exit_code'] = error.returncode
        record['service_job_failures'] = job_failures(error.stderr)
        record['service_states'] = getattr(error, '_sierx_service_states', None)
    return sanitize_exception(record)


def install():
    source = os.environ.get('SIERX_DIAGNOSTIC_DEPLOY')
    if not source or sys.argv[1:] != ['apply'] or os.path.abspath(sys.argv[0]) != source:
        return
    failure = None

    def on_event(frame, event, args):
        nonlocal failure
        if event != 'exception':
            return on_event
        kind, error, traceback = args
        if kind is SystemExit:
            if type(error.code) is int and error.code == 1 and failure is not None:
                try:
                    os.write(2, (MARKER + json.dumps(failure, separators=(',', ':')) + '\n').encode('ascii'))
                except OSError:
                    pass
            return on_event
        if (frame.f_code.co_name == 'main' and isinstance(error, subprocess.CalledProcessError)
                and isinstance(error.cmd, (list, tuple))
                and tuple(error.cmd[:3]) == ('systemctl', '--user', 'restart')
                and not hasattr(error, '_sierx_service_states')):
            error._sierx_service_states = capture_service_states()
        terminal = summarize_exception(error, traceback, source)
        if terminal is not None:
            earlier = error.__context__
            context = summarize_exception(earlier, earlier.__traceback__, source) if earlier else None
            failure = {'terminal': terminal}
            if context is not None:
                failure['context'] = context
        return on_event

    def trace_module(frame, event, _args):
        if (event == 'call' and frame.f_code.co_filename == source
                and frame.f_code.co_name in {'<module>', 'main'}):
            frame.f_trace_lines = False
            return on_event
        return None

    sys.settrace(trace_module)


if __name__ == 'sitecustomize':
    install()
