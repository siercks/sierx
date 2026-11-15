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
        terminal = summarize_exception(error, traceback, source)
        if terminal is not None:
            earlier = error.__context__
            context = summarize_exception(earlier, earlier.__traceback__, source) if earlier else None
            failure = {'terminal': terminal}
            if context is not None:
                failure['context'] = context
        return on_event

    def trace_module(frame, event, _args):
        if event == 'call' and frame.f_code.co_filename == source and frame.f_code.co_name == '<module>':
            frame.f_trace_lines = False
            return on_event
        return None

    sys.settrace(trace_module)


if __name__ == 'sitecustomize':
    install()
