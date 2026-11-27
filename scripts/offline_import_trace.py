"""Failure-only metadata before the unchanged bundle importer redacts errors."""
import json
import os
import subprocess
import sys

MARKER = 'SIERX_IMPORT_FAILURE: '
KINDS = {'CalledProcessError', 'FileNotFoundError', 'PermissionError', 'OSError',
         'ValueError', 'KeyError', 'TypeError', 'JSONDecodeError', 'UnicodeDecodeError'}
ROLES = {'app', 'caddy', 'postgres'}
STAGES = {'unknown', 'verify-bundle'} | {action + '-' + role for role in ROLES for action in ('load', 'inspect')}
PATTERNS = {
    'storage-configuration': ('database configuration mismatch',),
    'database-lock': ('database is locked',),
    'permission-denied': ('permission denied',),
    'operation-not-permitted': ('operation not permitted',),
    'storage-full': ('no space left on device',),
    'resource-unavailable': ('resource temporarily unavailable',),
    'namespace-clone': ('cannot clone',), 'reexec': ('cannot re-exec',),
    'uid-map': ('newuidmap', 'insufficient uids or gids'), 'gid-map': ('newgidmap',),
    'unsupported-format': ('unsupported manifest', 'unsupported image', 'unsupported media type'),
    'archive-format': ('invalid tar', 'invalid archive', 'unrecognized image format'),
    'digest-mismatch': ('digest mismatch', 'digest did not match', 'invalid checksum'),
    'source-initialization': ('initializing source',),
    'blob-write': ('writing blob',), 'layer-unpack': ('unpacking layer', 'applying layer'),
    'signature-policy': ('signature policy', 'policy.json',),
    'configuration-parse': ('decoding configuration', 'parsing configuration', 'unrecognized key', 'unsupported key'),
    'image-identity': ('loaded image identity or platform differs',),
    'image-revision': ('loaded application revision differs',),
    'missing-file': ('no such file or directory',), 'unexpected-eof': ('unexpected eof',),
}


def sanitize(value):
    if (not isinstance(value, dict) or not isinstance(value.get('kind'), str) or value['kind'] not in KINDS
            or not isinstance(value.get('stage'), str) or value['stage'] not in STAGES):
        return None
    lines = value.get('lines')
    if (not isinstance(lines, list) or not 1 <= len(lines) <= 8
            or any(type(n) is not int or not 1 <= n <= 100000 for n in lines)):
        return None
    result = {key: value[key] for key in ('kind', 'stage', 'lines')}
    code = value.get('exit_code')
    if value['kind'] == 'CalledProcessError' and (type(code) is not int or not -128 <= code <= 255):
        return None
    if type(code) is int and -128 <= code <= 255:
        result['exit_code'] = code
    categories = value.get('categories')
    if (not isinstance(categories, list) or len(categories) > len(PATTERNS)
            or any(not isinstance(name, str) or name not in PATTERNS for name in categories)
            or categories != sorted(set(categories))):
        return None
    result['categories'] = categories
    if (not isinstance(value.get('stderr_kind'), str) or value['stderr_kind'] not in {'text', 'bytes', 'unavailable'}
            or type(value.get('stderr_size')) is not int or not 0 <= value['stderr_size'] <= 0x7fffffff
            or type(value.get('stderr_tail_truncated')) is not bool):
        return None
    if value['stderr_kind'] == 'unavailable' and (value['stderr_size'] or value['stderr_tail_truncated'] or categories):
        return None
    if value['stderr_size'] > 8192 and not value['stderr_tail_truncated']:
        return None
    if value['stderr_kind'] == 'bytes' and value['stderr_size'] <= 8192 and value['stderr_tail_truncated']:
        return None
    result.update({key: value[key] for key in ('stderr_kind', 'stderr_size', 'stderr_tail_truncated')})
    return result


def summarize(error, traceback, source, frame, prior=None):
    lines = []
    while traceback is not None:
        if traceback.tb_frame.f_code.co_filename == source:
            lines.append(traceback.tb_lineno)
        traceback = traceback.tb_next
    role = None
    parent = frame
    while parent is not None:
        if parent.f_code.co_filename == source and parent.f_code.co_name == 'run_operation':
            candidate = parent.f_locals.get('role')
            role = candidate if isinstance(candidate, str) and candidate in ROLES else None
            break
        parent = parent.f_back
    stage = prior.get('stage', 'unknown') if prior else 'unknown'
    if isinstance(error, subprocess.CalledProcessError) and isinstance(error.cmd, (tuple, list)):
        if tuple(error.cmd[:2]) == ('podman', 'load') and role:
            stage = 'load-' + role
        elif tuple(error.cmd[:3]) == ('podman', 'image', 'inspect') and role:
            stage = 'inspect-' + role
    elif frame.f_code.co_name == 'inspect_image' and role:
        stage = 'inspect-' + role
    elif frame.f_code.co_name == 'verify':
        stage = 'verify-bundle'
    stderr = getattr(error, 'stderr', None)
    kind = 'text' if isinstance(stderr, str) else 'bytes' if isinstance(stderr, bytes) else 'unavailable'
    size = len(stderr) if kind != 'unavailable' else 0
    # Text counts are characters; byte counts are bytes. Inspect a bounded tail
    # only and state truncation explicitly. Neither raw data nor args escape.
    tail = stderr[-8192:] if kind != 'unavailable' else b''
    if isinstance(tail, str):
        tail = tail.encode('utf-8', errors='replace')
    truncated = size > 8192 or len(tail) > 8192
    text = tail[-8192:].decode('utf-8', errors='replace').lower()
    categories = sorted(name for name, patterns in PATTERNS.items() if any(pattern in text for pattern in patterns))
    value = {'kind': type(error).__name__, 'stage': stage, 'lines': lines[-8:],
             'categories': categories, 'stderr_kind': kind, 'stderr_size': size,
             'stderr_tail_truncated': truncated, 'exit_code': getattr(error, 'returncode', None)}
    return sanitize(value)


def stderr_failure(stderr):
    if not isinstance(stderr, bytes) or len(stderr) > 8192:
        return None
    prefix = MARKER.encode('ascii')
    rows = [line[len(prefix):] for line in stderr.splitlines() if line.startswith(prefix)]
    if len(rows) != 1 or len(rows[0]) > 2048:
        return None
    try:
        return sanitize(json.loads(rows[0]))
    except (ValueError, UnicodeError):
        return None


def install():
    source = os.environ.get('SIERX_DIAGNOSTIC_IMPORT')
    if not source or sys.argv[1:] != ['import'] or os.path.abspath(sys.argv[0]) != source:
        return
    failure = previous_error = None

    def on_event(frame, event, args):
        nonlocal failure, previous_error
        if event != 'exception':
            return on_event
        try:
            kind, error, traceback = args
            if kind is SystemExit:
                if frame.f_code.co_name == '<module>' and error.code not in (None, 0) and failure is not None:
                    os.write(2, (MARKER + json.dumps(failure, separators=(',', ':')) + '\n').encode('ascii'))
            else:
                value = summarize(error, traceback, source, frame, failure if previous_error is error else None)
                if value is not None:
                    failure, previous_error = value, error
        except Exception:
            # Optional observation cannot replace the original result or exit.
            failure = previous_error = None
        return on_event

    def trace(frame, event, args):
        if frame.f_code.co_filename == source:
            frame.f_trace_lines = False
            return on_event(frame, event, args)
        return None
    sys.settrace(trace)


if __name__ == 'sitecustomize':
    install()
