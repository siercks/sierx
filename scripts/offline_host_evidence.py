"""Fail-closed contract for the real rootless-installer acceptance report."""
import re
import math
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
             'browser_driver_policy':'seccomp-deny-io-uring','storage_driver':'overlay'}


def validate_browser(report):
    if (not isinstance(report, dict) or report.get('result') != 'passed'
            or not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', report.get('playwright', ''))
            or not isinstance(report.get('browsers'), list) or len(report['browsers']) != 2):
        raise ValueError('Missing delivered browser workflow evidence')
    driver=report.get('driver',{})
    if (not re.fullmatch(r'v24\.[0-9]+\.[0-9]+',driver.get('node',''))
            or driver.get('policy')!='seccomp-deny-io-uring' or driver.get('policy_verified') is not True
            or driver.get('external_fetch_control') is not True):
        raise ValueError('Browser driver configuration and its real controls are missing')
    for engine, result in zip(('chromium', 'firefox'), report['browsers']):
        if (result.get('engine') != engine or not result.get('version')
                or result.get('tls')!=('leaf-spki-pin' if engine=='chromium' else 'fixture-ca-nss')
                or result.get('checks') != BROWSER_CHECKS or type(result.get('external_requests')) is not int or result.get('external_requests') != 0
                or type(result.get('service_workers')) is not int or result.get('service_workers') != 0
                or result.get('observer_controls') != ['document', 'fetch', 'image', 'websocket']):
            raise ValueError('Incomplete delivered browser workflow or observation controls')


def validate(report, bundle, expected, suite_sha256):
    if (not isinstance(report, dict) or type(report.get('schema')) is not int or report.get('schema') != SCHEMA or report.get('suite') != SUITE
            or report.get('suite_sha256') != suite_sha256
            or not re.fullmatch(r'[a-f0-9]{64}', suite_sha256)
            or report.get('result') != 'passed' or report.get('arch') != bundle['arch']
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
            or report['attempts_examined']<sum(report['negative_controls'].values())):
        raise ValueError('Missing attempted-connection coverage or real negative controls')
    if (report.get('browser_driver_policy')!='seccomp-deny-io-uring'
            or type(report.get('blocked_io_uring_setups')) is not int or report['blocked_io_uring_setups']<1):
        raise ValueError('Browser driver asynchronous I/O policy was not observed')


def validate_closeout(report,bundle,expected,suite_sha256):
    validate(report,bundle,expected,suite_sha256)
    validate_network(report.get('network'))
    if (report['coverage']!='closeout' or report.get('virtual_cpu') not in {'kvm','tcg'}
            or any(not re.fullmatch(r'[a-f0-9]{64}',report.get(name,'')) for name in ('rootfs_sha256','kernel_sha256','archive_sha256'))):
        raise ValueError('Development evidence cannot satisfy closeout promotion')
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
