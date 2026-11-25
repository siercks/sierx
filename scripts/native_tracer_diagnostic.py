"""Nonpromotable causal checks for a real historical installer import."""
import hashlib
import re
from tracer_diagnostic import ARCHIVE_SHA256, PATCH_SHA256, SOURCE_SHA256

# The same observation is compiled into BOTH controls. It executes the original
# call once, records only failed query metadata, and restores returned errno.
# It never injects a syscall result and is never used by release guest builds.
QUERY_OBSERVATION = b'''({
    long sierx_query_result = ptrace(PTRACE_GETSIGINFO, pid, 0, &wd->si);
    if (sierx_query_result < 0) {
        const int sierx_query_errno = errno;
        fprintf(stderr, "SIERX_PTRACE_QUERY pid=%d errno=%d\\n",
                (int) pid, sierx_query_errno);
        errno = sierx_query_errno;
    }
    sierx_query_result;
})'''
OBSERVATION_SHA256 = hashlib.sha256(QUERY_OBSERVATION).hexdigest()
OBSERVED_SOURCE_SHA256 = {
    'old':'0ce1386b760eff252ce029b3d3c7e5d27144c8311339bc7c4aeaadbb89bdec1f',
    'fixed':'87f005169f5abb35588fc46fd65ae7a7244a60ae72e14b23c27cabcb48842601'}
CONFIGURE_FLAGS = ['--enable-mpers=no','--with-libunwind=no','--with-libdw=no','--with-libiberty=no']


def observe_queries(source, mode):
    if hashlib.sha256(source).hexdigest() != SOURCE_SHA256[mode]:
        raise ValueError('Query observation requires exact pinned tracer source')
    pattern = rb'ptrace\(PTRACE_GETSIGINFO,\s*pid,\s*0,\s*&wd->si\)'
    matches=list(re.finditer(pattern,source))
    if len(matches)!=1:raise ValueError('Ambiguous tracer query observation point')
    match=matches[0]
    observed=source[:match.start()]+QUERY_OBSERVATION+source[match.end():]
    if hashlib.sha256(observed).hexdigest()!=OBSERVED_SOURCE_SHA256[mode]:
        raise ValueError('Observed control differs from the reviewed source bytes')
    return observed


def query_failure_fields(text):
    """Discard PIDs and all raw messages after checking the exact target pair."""
    if not isinstance(text,str) or len(text.encode())>65536:
        return {'capture':'invalid-or-truncated'}
    queries=[];pairs=[];listens=0;malformed=False
    for index,line in enumerate(text.splitlines()):
        if line.startswith('SIERX_PTRACE_QUERY'):
            match=re.fullmatch(r'SIERX_PTRACE_QUERY pid=([1-9][0-9]{0,9}) errno=([1-9][0-9]{0,3})',line)
            if not match or int(match[1])>2147483647 or int(match[2])>4095:malformed=True;continue
            queries.append((index,int(match[1]),int(match[2])))
        match=re.fullmatch(r'(?:strace|/usr/bin/strace): ptrace\(PTRACE_LISTEN,pid:([1-9][0-9]{0,9}),sig:[0-9]+\): Input/output error',line)
        if match:
            if int(match[1])>2147483647:malformed=True;continue
            listens+=1
            matching=[row for row in queries if row[1]==int(match[1]) and row[2]==3]
            if len(matching)==1:pairs.append((matching[0][0],index))
    return {'capture':'invalid-or-truncated' if malformed else 'observed',
            'failed_queries':len(queries),'esrch_queries':sum(row[2]==3 for row in queries),
            'listen_eio':listens,'unique_same_target_pair':len(pairs)==1 and listens==1}


def valid_query_counts(query):
    return (all(type(query.get(key)) is int and 0<=query[key]<=65536
                for key in ('failed_queries','esrch_queries','listen_eio'))
            and query['esrch_queries']<=query['failed_queries'])


def expected_old_failure(report):
    observation=report.get('observation',{})
    query=report.get('query_observation',{})
    errors=observation.get('tracer_syscall_errors',[])
    pairs=[]
    if isinstance(errors,list):
        for first,second in zip(errors,errors[1:]):
            if (all(isinstance(row,dict) and row.get('call')=='ptrace'
                    and type(row.get('age_ms')) is int and 0<=row['age_ms']<=2000 for row in (first,second))
                    and first.get('errno')==3 and second.get('errno')==5
                    and first['age_ms']>=second['age_ms']):pairs.append((first,second))
    expected={role:{'task_exited':True} for role in ('installer','import-helper')}
    expected['tracer']={'task_exited':True,'requested_exit_code':1}
    return (report.get('result')=='failed' and type(report.get('tracer_returncode')) is int
        and report['tracer_returncode']==1 and query.get('capture')=='observed'
        and query.get('unique_same_target_pair') is True and valid_query_counts(query)
        and query['esrch_queries']>=1 and query['listen_eio']==1 and len(pairs)==1
        and observation.get('kernel_exit_capture')=='observed'
        and observation.get('kernel_exit')==expected
        and all(task.get('task_exited') is True and
                ('requested_exit_code' not in task or type(task['requested_exit_code']) is int)
                for task in observation['kernel_exit'].values()))


def expected_fixed_completion(report):
    observation=report.get('observation',{})
    expected={role:{'task_exited':True,'requested_exit_code':0}
              for role in ('installer','tracer','import-helper')}
    return (report.get('result')=='passed' and type(report.get('tracer_returncode')) is int
        and report['tracer_returncode']==0 and observation.get('import_stage')=='import-complete'
        and observation.get('kernel_exit_capture')=='observed' and observation.get('kernel_exit')==expected
        and report.get('query_observation',{}).get('capture')=='observed'
        and valid_query_counts(report['query_observation'])
        and report['query_observation'].get('listen_eio')==0
        and all(task.get('task_exited') is True and type(task.get('requested_exit_code')) is int
                for task in observation['kernel_exit'].values()))


def validate_build(build):
    if (build.get('source_archive_sha256')!=ARCHIVE_SHA256 or build.get('patch_sha256')!=PATCH_SHA256
            or build.get('observation_sha256')!=OBSERVATION_SHA256
            or build.get('configure_flags')!=CONFIGURE_FLAGS
            or build.get('release_acceptance') is not False
            or set(build.get('builds',{}))!={'old','fixed'}):
        raise ValueError('Mismatched observed tracer controls')
    for mode,row in build['builds'].items():
        if (row.get('base_source_sha256')!=SOURCE_SHA256[mode] or row.get('version')!='6.8'
                or row.get('observed_source_sha256')!=OBSERVED_SOURCE_SHA256[mode]
                or any(not isinstance(row.get(key),str) or not re.fullmatch('[a-f0-9]{64}',row[key])
                       for key in ('sha256','observed_source_sha256'))):
            raise ValueError('Missing exact tracer source and binary bindings')
    if build['builds']['old']['sha256']==build['builds']['fixed']['sha256']:
        raise ValueError('Compared tracer binaries must differ')


def public_build(build):
    validate_build(build)
    return {**{key:build[key] for key in ('source_archive_sha256','patch_sha256','observation_sha256',
        'configure_flags','release_acceptance')},'builds':{mode:{key:row[key] for key in (
            'sha256','base_source_sha256','observed_source_sha256','version')} for mode,row in build['builds'].items()}}


def public_case(report):
    """Build the public case from fixed fields, never copy a private object."""
    import offline_host_diagnostics as diagnostics
    if (report.get('suite')!='offline-native-import-probe-v1'
            or report.get('release_acceptance') is not False or report.get('result') not in {'passed','failed'}
            or type(report.get('tracer_returncode')) is not int or not -128<=report['tracer_returncode']<=255
            or not isinstance(report.get('kernel_release'),str)
            or not re.fullmatch(r'[A-Za-z0-9.+_-]{1,128}',report['kernel_release'])
            or report.get('fresh_rootless_overlay') is not True or report.get('loopback_only') is not True
            or report.get('installer_trace_mode')!='ordinary-ptrace'
            or any(not isinstance(report.get(key),str) or not re.fullmatch('[a-f0-9]{64}',report[key])
                   for key in ('strace_sha256','podman_sha256'))):
        raise ValueError('Malformed native case metadata')
    observation=report.get('observation')
    if not isinstance(observation,dict):raise ValueError('Missing native task evidence')
    safe=diagnostics.sanitize_failure({**observation,'result':'failed','phase':'import','failure_source':'service-exit'})
    safe={key:value for key,value in safe.items() if key not in {'result','phase','failure_type','failure_source'}}
    query=report.get('query_observation')
    if not isinstance(query,dict) or query.get('capture') not in {'observed','invalid-or-truncated'}:
        raise ValueError('Missing bounded source query observation')
    public_query={'capture':query['capture']}
    for key in ('failed_queries','esrch_queries','listen_eio'):
        value=query.get(key)
        if type(value) is int and 0<=value<=65536:public_query[key]=value
    if type(query.get('unique_same_target_pair')) is bool:
        public_query['unique_same_target_pair']=query['unique_same_target_pair']
    return {**{key:report[key] for key in ('suite','release_acceptance','result','tracer_returncode',
        'strace_sha256','podman_sha256','kernel_release','fresh_rootless_overlay','loopback_only','installer_trace_mode')},
        'observation':safe,'query_observation':public_query}
