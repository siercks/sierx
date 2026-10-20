"""Fail-closed contract for the real rootless-installer acceptance report."""
import re
import math
import json
from network_observer import CONTROLS, PROCESSES

SCHEMA = 2
SUITE = 'offline-host-v2'
CHECKS = ['checksum-approved-delivery-archive','rootless-import', 'real-quadlet-db', 'migrations-bootstrap', 'actual-plan-apply',
          'provided-tls-login-write-deep-link', 'repeat-apply-noop', 'all-service-restart-persistence',
          'delivered-browser-workflows','observed-connection-attempts']
CLOSEOUT_CHECKS = ['invalid-deliveries','two-approved-releases','failed-health-rollback',
                   'bounded-runtime','explicit-opt-in-acquisition']
INVALID_DELIVERIES = ['missing-image','altered-archive','wrong-architecture','wrong-digest',
                      'missing-certificate','empty-image-store']
DATA_TABLES = ['workspace','user_account','membership','project','project_config','status','item_type',
               'config_status','config_type','config_transition','field_def','item','item_rollup',
               'item_link','change_event','seq_counter','sprint','sprint_item','comment','saved_view']
BROWSER_CHECKS = ['login', 'create-edit-project', 'create-edit-item', 'transition', 'comment', 'link',
                  'query-reload', 'cold-bootstrap', 'canonical-deep-link']
ISOLATION = {'network':'loopback-only', 'system_manager':'private-vm', 'user_manager':'real-systemd',
             'rootless':True, 'fresh_image_store':True, 'network_devices':0,
             'browser_driver_policy':'seccomp-deny-io-uring','storage_driver':'overlay',
             'rootless_network':'slirp4netns','browser_address_families':['AF_UNIX','AF_INET','AF_NETLINK']}


def browser_failure_diagnostic(text):
    """Extract only fixed failure labels; private messages/stack traces stay private."""
    phases = {'launch','driver-policy','firefox-network-launch'} | {
        engine+'-'+stage for engine in ('chromium','firefox') for stage in (
            'launch','context-setup','new-page','login','create-project','edit-project','create-edit-transition-comment-link',
            'login-navigation','login-fields','login-submit','login-ready',
            'create-item','create-item-submit','create-item-response','create-item-ready',
            'edit-item','transition','comment','create-link-target','link',
            'search-reload-bootstrap','guard-controls','network-control')}
    errors = {'Error','TimeoutError','AssertionError','TypeError','ProtocolError','TargetClosedError'}
    for phase, error in re.findall(r'^offline-browser: failed at ([a-z-]+) \(([A-Za-z]+)\); no passing report$', text, re.MULTILINE):
        if phase in phases and error in errors:
            result = phase+' ('+error+')'
            reason = re.search(r'^offline-browser: reason (ambiguous-locator|wait-timeout|assertion-failed|operation-failed|recovery-unavailable)$',text,re.MULTILINE)
            matcher = re.search(r'^offline-browser: matcher (toBeVisible|toBeHidden|toHaveValue|toHaveURL|toContainText|toHaveCount|toEqual)$',text,re.MULTILINE)
            statuses = sorted(set(re.findall(r'^offline-browser: http-status ([45][0-9]{2})$',text,re.MULTILINE)))[:10]
            if reason:result += ' reason='+reason[1]
            if matcher:result += ' matcher='+matcher[1]
            if statuses:result += ' http='+','.join(statuses)
            kinds=sorted(set(re.findall(r'^offline-browser: unavailable ((?:GET|POST|PATCH|PUT|DELETE|HEAD)-(?:recovery|problem|other))$',text,re.MULTILINE)))
            if kinds:result += ' unavailable='+','.join(kinds)
            late=early=timeouts=0
            for line in text.splitlines():
                try:
                    record=json.loads(line[line.index('{'):])
                except (ValueError,TypeError):
                    continue
                if (isinstance(record,dict) and record.get('msg')=='lifecycle verification rejected request'
                        and record.get('reason')=='deadline-exceeded'):
                    timeouts+=1
                if (isinstance(record,dict) and record.get('msg')=='request' and record.get('route')=='unmatched'
                        and record.get('status')==503 and type(record.get('duration_ms')) is int and record['duration_ms']>=0):
                    if record['duration_ms']>=1000:late+=1
                    else:early+=1
            if late or early:result += ' recovery-late='+str(late)+' recovery-early='+str(early)
            if timeouts:result += ' recovery-timeouts='+str(timeouts)
            return result
    return None


def control_failure_diagnostic(text):
    messages = {
        'Synthetic network command exceeded its bounded timeout':'control-command-timeout',
        'Network negative control exceeded its bounded interval':'control-window-timeout',
        'Synthetic application must fail on its forbidden database connection':'application-control-did-not-fail',
        'Planted forbidden connection unexpectedly succeeded':'forbidden-control-succeeded',
        'Gateway negative-control listener did not start':'gateway-control-not-ready',
    }
    for message, label in messages.items():
        if re.search(r'^ValueError: '+re.escape(message)+r'$', text, re.MULTILINE):
            return label
    return None


def validate_browser(report):
    if (not isinstance(report, dict) or report.get('result') != 'passed'
            or not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', report.get('playwright', ''))
            or not isinstance(report.get('browsers'), list) or len(report['browsers']) != 2):
        raise ValueError('Missing delivered browser workflow evidence')
    driver=report.get('driver',{})
    if (not re.fullmatch(r'v24\.[0-9]+\.[0-9]+',driver.get('node',''))
            or driver.get('policy')!='seccomp-deny-io-uring' or driver.get('policy_verified') is not True
            or driver.get('external_fetch_control') is not True or driver.get('ipv4_only_verified') is not True
            or type(driver.get('recovery_read_retries')) is not int or not 0<=driver['recovery_read_retries']<=10):
        raise ValueError('Browser driver configuration and its real controls are missing')
    for engine, result in zip(('chromium', 'firefox'), report['browsers']):
        if (result.get('engine') != engine or not result.get('version')
                or result.get('tls')!=('leaf-spki-pin' if engine=='chromium' else 'fixture-ca-nss')
                or result.get('checks') != BROWSER_CHECKS or type(result.get('external_requests')) is not int or result.get('external_requests') != 0
                or type(result.get('service_workers')) is not int or result.get('service_workers') != 0
                or result.get('observer_controls') != ['document','document-ipv6', 'fetch', 'image', 'websocket']):
            raise ValueError('Incomplete delivered browser workflow or observation controls')


def validate(report, bundle, expected, suite_sha256):
    if (not isinstance(report, dict) or type(report.get('schema')) is not int or report.get('schema') != SCHEMA or report.get('suite') != SUITE
            or report.get('suite_sha256') != suite_sha256
            or not re.fullmatch(r'[a-f0-9]{64}', suite_sha256)
            or report.get('result') != 'passed' or report.get('arch') != bundle['arch']
            or type(report.get('virtual_cpus')) is not int or report['virtual_cpus'] not in {2,4}
            or type(report.get('lifecycle_check_timeout_seconds')) is not int or report['lifecycle_check_timeout_seconds'] not in {1,10}
            or report.get('release') != bundle['release'] or report.get('bundle_sha256') != expected
            or report.get('coverage') not in {'development','closeout'}
            or report.get('checks') != CHECKS + (CLOSEOUT_CHECKS if report.get('coverage')=='closeout' else [])
            or report.get('isolation') != ISOLATION
            or report.get('isolation',{}).get('rootless') is not True
            or report.get('isolation',{}).get('fresh_image_store') is not True
            or type(report.get('isolation',{}).get('network_devices')) is not int
            or not re.fullmatch(r'(?:ubuntu-24\.04|rocky-10(?:\.[0-9]+)?)', report.get('profile', ''))):
        raise ValueError('Missing, incomplete or mismatched real rootless-installer evidence')
    validate_browser(report.get('browser'))
    versions=report.get('host_versions',{})
    if (set(versions)!={'kernel','systemd','podman','selinux'}
            or any(not isinstance(value,str) or not value or len(value)>256 or '\n' in value or '\r' in value for value in versions.values())
            or versions['selinux'] not in {'disabled','permissive','enforcing'}):
        raise ValueError('Missing actual host software/profile versions')


def validate_network(report):
    if (not isinstance(report,dict) or report.get('result')!='passed'
            or report.get('observer')!='strace-network-v1' or report.get('processes')!=sorted(PROCESSES)
            or type(report.get('external_attempts')) is not int or report['external_attempts']!=0
            or not isinstance(report.get('negative_controls'),dict)
            or set(report['negative_controls'])!=set(CONTROLS)
            or any(type(count) is not int or count<1 for count in report['negative_controls'].values())
            or type(report.get('attempts_examined')) is not int
            or report['attempts_examined']<sum(report['negative_controls'].values())
            or type(report.get('control_interval_limit_seconds')) is not int
            or report['control_interval_limit_seconds'] not in {20,120}):
        raise ValueError('Missing attempted-connection coverage or real negative controls')
    if (report.get('browser_driver_policy')!='seccomp-deny-io-uring'
            or type(report.get('blocked_io_uring_setups')) is not int or report['blocked_io_uring_setups']<1
            or type(report.get('blocked_ipv6_sockets')) is not int or report['blocked_ipv6_sockets']<1):
        raise ValueError('Browser driver asynchronous I/O policy was not observed')


def validate_closeout(report,bundle,expected,suite_sha256):
    validate(report,bundle,expected,suite_sha256)
    validate_network(report.get('network'))
    if (report['coverage']!='closeout' or report.get('virtual_cpu') not in {'kvm','tcg'}
            or any(not re.fullmatch(r'[a-f0-9]{64}',report.get(name,'')) for name in ('rootfs_sha256','kernel_sha256','archive_sha256'))):
        raise ValueError('Development evidence cannot satisfy closeout promotion')
    emulated = report['virtual_cpu']=='tcg'
    if (report['virtual_cpus'] != (4 if emulated else 2)
            or report['lifecycle_check_timeout_seconds'] != (10 if emulated else 1)
            or report['network']['control_interval_limit_seconds'] != (120 if emulated else 20)
            or report['browser']['driver'].get('timing_mode') != ('software-emulation' if emulated else 'standard')
            or (not emulated and report['browser']['driver']['recovery_read_retries'] != 0)):
        raise ValueError('Fixture timing budgets differ from the recorded acceleration mode')
    scenarios=report.get('scenarios',{})
    if set(scenarios)!={'invalid_deliveries','two_release','failed_health','runtime','acquisition'}:
        raise ValueError('Missing required real installer scenarios')
    if scenarios['invalid_deliveries']!=INVALID_DELIVERIES:
        raise ValueError('Missing invalid-delivery rejection controls')
    releases=scenarios['two_release']
    if (releases.get('candidate')!=bundle['release'] or releases.get('previous',{}).get('revision')==bundle['release']['revision']
            or not re.fullmatch(r'[a-f0-9]{40}',releases.get('previous',{}).get('revision',''))
            or not re.fullmatch(r'[A-Za-z0-9._:/-]+@sha256:[a-f0-9]{64}',releases.get('previous',{}).get('image',''))
            or not re.fullmatch(r'[a-f0-9]{64}',releases.get('previous_bundle_sha256',''))
            or type(releases.get('schema_before')) is not int or releases['schema_before']<1
            or releases.get('schema_after')!=releases['schema_before']
            or releases.get('data_scope')!=DATA_TABLES
            or any(releases.get(name) is not True for name in ('fingerprint_preserved','update','compatible_rollback'))):
        raise ValueError('Two distinct approved releases and compatible schema/data rollback are required')
    flags={'rejected','candidate_started','candidate_health_failed','accepted_revision_preserved','configuration_restored','data_preserved'}
    health=scenarios['failed_health']
    if set(health)!=flags or any(health[name] is not True for name in flags):
        raise ValueError('Failed health must restore the previous accepted release and data')
    runtime=scenarios['runtime']
    elapsed=runtime.get('elapsed_seconds')
    if (type(runtime.get('seconds')) is not int or not 120<=runtime['seconds']<=180
            or type(elapsed) not in {int,float} or not math.isfinite(elapsed) or not 120<=elapsed<=180
            or type(runtime.get('change_feed_polls')) is not int or runtime['change_feed_polls']<3
            or runtime.get('maintenance_timer_triggered') is not True or runtime.get('offline_timer_modes_rejected')!=5):
        raise ValueError('Bounded runtime and actual timer-trigger evidence is missing')
    for name in ('services','timers','enabled_units'):
        units=runtime.get(name)
        if (not isinstance(units,list) or len(units)>512
                or any(not isinstance(unit,str) or not re.fullmatch(r'[A-Za-z0-9@_.:\\\-]{1,256}',unit) for unit in units)
                or 'sierx-pull.timer' in units):
            raise ValueError('Invalid runtime unit inventory or an unsolicited acquisition timer')
    if not {'sierx.service','sierx-caddy.service','sierx-postgres.service'}.issubset(runtime['services']):
        raise ValueError('Runtime inventory omits actual installed services')
    acquisition=scenarios['acquisition']
    if (acquisition.get('result')!='passed' or acquisition.get('source')!='synthetic-loopback-registry'
            or any(acquisition.get(name) is not True for name in ('opt_in','https_verified','empty_store','image_identity_verified'))
            or any(type(acquisition.get(name)) is not int or acquisition[name]<1 for name in ('manifest_requests','blob_requests'))):
        raise ValueError('Missing explicit trusted HTTPS acquisition control')
