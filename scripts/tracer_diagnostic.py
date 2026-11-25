"""Bounds and safe summaries for the standalone tracer mechanism diagnostic."""
import json
import os
from pathlib import Path
import platform
import pwd
import re

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT/'test/diagnostics/tracer-termination'
ARCHIVE_SHA256 = 'ba6950a96824cdf93a584fa04f0a733896d2a6bc5f0ad9ffe505d9b41e970149'
PATCH_SHA256 = 'f46bb4fa62dd8b039ab27c8d74c9fdb7ed816a3b6814f0fa2448dd75b304f1f9'
SOURCE_SHA256 = {'old':'21fe0b653612b9354ff783a9ca1643d39682d85fd38bf32a14b09cdea41febd1',
                 'fixed':'c54b2296cfffb9dc745fc99cdb54ca5588c8be3a57adde57d7600d7fe27497e6'}


def architecture():
    value = {'x86_64':'amd64', 'aarch64':'arm64'}.get(platform.machine())
    if value is None: raise ValueError('Unsupported diagnostic architecture')
    return value


def state_directory():
    value = Path(os.environ['SIERX_TRACER_DIAGNOSTIC_STATE'])
    if (not value.is_absolute() or value.is_symlink() or (ROOT/'dist').is_symlink()
            or value.resolve().parent != (ROOT/'dist').resolve()
            or not re.fullmatch(r'tracer-race-(?:amd64|arm64)(?:-local)?', value.name)):
        raise ValueError('Diagnostic state must be an explicit owned dist directory')
    return value.resolve()


def target_user(build):
    user = os.environ['SIERX_TRACER_DIAGNOSTIC_USER']
    if not re.fullmatch(r'[a-z_][a-z0-9_-]{0,31}',user):
        raise ValueError('Invalid diagnostic account')
    uid = pwd.getpwnam(user).pw_uid
    if (uid == 0 or type(build.get('owner_uid')) is not int or uid != build['owner_uid']
            or build.get('arch') != architecture()):
        raise ValueError('Diagnostic account differs from the unprivileged preparer')
    return user


def clean_environment(scratch):
    return {'PATH':'/usr/bin:/bin','HOME':str(scratch),'LANG':'C.UTF-8','LC_ALL':'C',
            'PYTHONDONTWRITEBYTECODE':'1'}


def safe_probe_progress(path):
    """Only fixed labels/status survive a failed child's private progress log."""
    try:
        with Path(path).open('rb') as stream:
            stream.seek(0,os.SEEK_END)
            stream.seek(max(0,stream.tell()-16384))
            lines=stream.read(16384).decode(errors='replace').splitlines()
    except OSError:
        return None
    for line in reversed(lines):
        try: row=json.loads(line)
        except ValueError: continue
        if not isinstance(row,dict):continue
        label=row.get('case')
        if label not in {'old-ordinary','old-seccomp','fixed-ordinary','fixed-seccomp'}:
            if row.get('mode') not in {'old','fixed'}:continue
            label='natural-'+row['mode']
        result={'case':label}
        code=row.get('tracer_return',row.get('return_code'))
        if type(code) is int and -255<=code<=255:result['tracer_return']=code
        for key in ('forced_query_esrch_observed','subsequent_listen_eio_observed',
                    'installer_survived','deadline_reached','completed_4096','listen_eio'):
            if type(row.get(key)) is bool:result[key]=row[key]
        kernel=row.get('kernel')
        capture=row.get('kernel_exit_capture')
        if isinstance(kernel,dict):capture=kernel.get('kernel_exit_capture',capture)
        if capture in {'observed','unavailable','lost-events','invalid-records'}:
            result['kernel_exit_capture']=capture
        return result
    return None


def verify_result(build, controlled, natural, revision):
    if (not re.fullmatch(r'[a-f0-9]{40}',revision)
            or build.get('source_archive_sha256') != ARCHIVE_SHA256
            or build.get('patch_sha256') != PATCH_SHA256
            or build.get('system_binary_replaced') is not False
            or build.get('release_acceptance') is not False
            or build.get('arch') != architecture()):
        raise ValueError('Mismatched diagnostic build inputs')
    binaries = {}
    if set(build.get('builds',{})) != {'old','fixed'}:
        raise ValueError('Both matched tracer builds are required')
    for mode in ('old','fixed'):
        binary = build['builds'][mode]
        if (not re.fullmatch(r'[a-f0-9]{64}',binary.get('sha256',''))
                or binary.get('source_sha256') != SOURCE_SHA256[mode] or binary.get('version') != '6.8'):
            raise ValueError('Mismatched tracer source or binary hash')
        binaries[mode] = {key:binary[key] for key in ('sha256','source_sha256','version')}
    if binaries['old']['sha256'] == binaries['fixed']['sha256']:
        raise ValueError('The compared binaries must be distinct')
    if controlled.get('build') != build or natural.get('build') != build:
        raise ValueError('Probe results refer to different builds')
    rows = controlled.get('cases')
    expected = ['old-ordinary','old-seccomp','fixed-ordinary','fixed-seccomp']
    if not isinstance(rows,list) or [row.get('case') for row in rows] != expected:
        raise ValueError('All four controlled comparisons are required')
    for row in rows:
        fixed = row['case'].startswith('fixed-')
        roles = {role:{'task_exited':True,'requested_exit_code':0} for role in ('installer','tracer')}
        if not fixed:
            roles = {'installer':{'task_exited':True},'tracer':{'task_exited':True,'requested_exit_code':1}}
        if (row.get('forced_query_esrch_observed') is not True
                or row.get('subsequent_listen_eio_observed') is not (not fixed)
                or type(row.get('tracer_return')) is not int or row.get('tracer_return') != (0 if fixed else 1)
                or row.get('installer_survived') is not fixed
                or row.get('kernel_exit_capture') != 'observed' or row.get('kernel_exit') != roles):
            raise ValueError('Incomplete controlled mechanism evidence')
        for role,task in row['kernel_exit'].items():
            if task.get('task_exited') is not True:
                raise ValueError('Task death must be a genuine boolean observation')
            if 'requested_exit_code' in task and type(task['requested_exit_code']) is not int:
                raise ValueError('Invalid task exit code')
    if controlled.get('release_acceptance') is not False or controlled.get('historical_cause_proven') is not False:
        raise ValueError('A diagnostic cannot approve a historical release')
    rows = natural.get('cases')
    if (not isinstance(rows,list) or len(rows) != 2 or rows[0].get('mode') != 'old'
            or rows[1].get('mode') != 'fixed' or natural.get('fault_injection') is not False
            or natural.get('natural_failure_reproduced') is not True
            or natural.get('narrow_fix_verified_on_natural_workload') is not True
            or natural.get('historical_cause_proven') is not False
            or natural.get('release_acceptance') is not False):
        raise ValueError('A natural old-versus-fixed comparison is required')
    old,fixed = rows
    if (any(type(row.get('tracer_return')) is not int for row in rows)
            or old.get('tracer_return') != 1 or old.get('listen_eio') is not True
            or fixed.get('tracer_return') != 0 or fixed.get('listen_eio') is not False
            or fixed.get('completed_4096') is not True
            or any(row.get('fault_injection') is not False or row.get('deadline_reached') is not False
                   or row.get('kernel',{}).get('kernel_exit_capture') != 'observed' for row in rows)
            or old['kernel'].get('kernel_exit') != {
                'installer':{'task_exited':True},'tracer':{'task_exited':True,'requested_exit_code':1}}
            or fixed['kernel'].get('kernel_exit') != {
                role:{'task_exited':True,'requested_exit_code':0} for role in ('installer','tracer')}):
        raise ValueError('Incomplete natural mechanism or correction evidence')
    for row in rows:
        for task in row['kernel']['kernel_exit'].values():
            if task.get('task_exited') is not True:
                raise ValueError('Natural task death must be a genuine boolean observation')
            if 'requested_exit_code' in task and type(task['requested_exit_code']) is not int:
                raise ValueError('Invalid natural task exit code')
    controlled_rows = [{key:row[key] for key in ('case','forced_query_esrch_observed',
        'subsequent_listen_eio_observed','tracer_return','installer_survived',
        'kernel_exit_capture','kernel_exit')} for row in controlled['cases']]
    natural_rows = [{**{key:row[key] for key in ('mode','tracer_return','deadline_reached',
        'completed_4096','listen_eio','fault_injection')}, 'kernel':{
            key:row['kernel'][key] for key in ('kernel_exit_capture','kernel_exit')}} for row in rows]
    return {'schema':1,'suite':'tracer-termination-diagnostic-v1','revision':revision,
            'arch':architecture(),'result':'passed','release_acceptance':False,
            'historical_cause_proven':False,'source_archive_sha256':ARCHIVE_SHA256,
            'patch_sha256':PATCH_SHA256,'controlled_cases':controlled_rows,
            'natural_cases':natural_rows,'fixed_completed_cycles':4096,
            'system_binary_replaced':False,'binaries':binaries}
