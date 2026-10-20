"""Complete synthetic reports for rejection tests, never acceptance artifacts."""
import offline_host_evidence as evidence
from network_observer import CONTROLS, PROCESSES


def full_host_report(bundle,expected,suite,profile,previous):
    return {**bundle,'schema':evidence.SCHEMA,'suite':evidence.SUITE,'suite_sha256':suite,
        'result':'passed','bundle_sha256':expected,'profile':profile,'coverage':'closeout',
        'checks':evidence.CHECKS+evidence.CLOSEOUT_CHECKS,'isolation':evidence.ISOLATION,
        'virtual_cpu':'kvm','virtual_cpus':2,'lifecycle_check_timeout_seconds':1,'rootfs_sha256':'c'*64,'kernel_sha256':'d'*64,'archive_sha256':'e'*64,
        'host_versions':{'kernel':'6.8.0-fixture','systemd':'systemd 255','podman':'podman version 4.9.3','selinux':'disabled'},
        'browser':{'result':'passed','playwright':'1.63.0','driver':{'node':'v24.22.0','policy':'seccomp-deny-io-uring',
            'policy_verified':True,'external_fetch_control':True,'ipv4_only_verified':True,'timing_mode':'standard','recovery_read_retries':0},'browsers':[
            {'engine':engine,'version':'1.0.0','checks':evidence.BROWSER_CHECKS,'external_requests':0,
             'tls':'leaf-spki-pin' if engine=='chromium' else 'fixture-ca-nss',
             'service_workers':0,'observer_controls':['document','document-ipv6','fetch','image','websocket']}
            for engine in ('chromium','firefox')]},
        'network':{'result':'passed','observer':'strace-network-v1','processes':sorted(PROCESSES),
            'external_attempts':0,'negative_controls':{name:1 for name in CONTROLS},'attempts_examined':len(CONTROLS),
            'browser_driver_policy':'seccomp-deny-io-uring','blocked_io_uring_setups':1,'blocked_ipv6_sockets':1,
            'control_interval_limit_seconds':20},
        'scenarios':{'invalid_deliveries':evidence.INVALID_DELIVERIES,
            'two_release':{'previous':previous['release'],'previous_bundle_sha256':previous['bundle_sha256'],
                'candidate':bundle['release'],'schema_before':15,'schema_after':15,'fingerprint_preserved':True,
                'update':True,'compatible_rollback':True,'data_scope':evidence.DATA_TABLES},
            'failed_health':{name:True for name in ('rejected','candidate_started','candidate_health_failed',
                'accepted_revision_preserved','configuration_restored','data_preserved')},
            'runtime':{'seconds':120,'elapsed_seconds':120.5,'change_feed_polls':24,'maintenance_timer_triggered':True,
                'offline_timer_modes_rejected':5,'services':['sierx.service','sierx-caddy.service','sierx-postgres.service'],
                'timers':['sierx-acceptance-maintenance.timer'],'enabled_units':[]},
            'acquisition':{'result':'passed','opt_in':True,'source':'synthetic-loopback-registry','https_verified':True,
                'empty_store':True,'image_identity_verified':True,'manifest_requests':1,'blob_requests':1}}}
