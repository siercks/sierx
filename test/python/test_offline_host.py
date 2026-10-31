"""Reject stale evidence and hostile OS archives before launching a guest."""
import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
import offline_host_evidence as evidence
from offline_host_fixture import full_host_report

spec = importlib.util.spec_from_file_location('host_fixture', ROOT / 'scripts/offline-host.py')
host = importlib.util.module_from_spec(spec)
spec.loader.exec_module(host)


class EvidenceTests(unittest.TestCase):
    def test_failed_guest_summary_survives_runner_cleanup_and_cannot_satisfy_acceptance(self):
        with tempfile.TemporaryDirectory() as temporary:
            report=Path(temporary)/'host-acceptance-ubuntu24-arm64.json'
            raw={'result':'failed','phase':'delivered-browser-workflows','failure_type':'JSONDecodeError',
                 'json_input':'empty','json_chars':0,'json_position':0,'private':'credential'}
            result=host.record_failure(report,raw,b'private journal and credential','arm64','c'*64,'a'*40)
            saved=json.loads(report.with_suffix('.failure.json').read_text())
            self.assertEqual(result['failure_type'],'JSONDecodeError')
            self.assertEqual(saved['result'],'failed')
            self.assertEqual(saved['suite'],'offline-host-failure-v1')
            self.assertEqual(saved['revision'],'a'*40)
            self.assertFalse(report.exists())
            self.assertNotIn('private',json.dumps(saved))
            with self.assertRaises(ValueError):evidence.validate(saved,self.bundle,'d'*64,'c'*64)

    def test_trace_file_boundary_preserves_each_startup_record(self):
        import network_observer as observer
        manager = b'10<systemd> 1.000000 close(3) = 0'
        installer = b'20<runner> 2.000000 execve("/usr/local/bin/sierx", ["fixture"], 0x0) = 0\n'
        # A collector can end without a newline. Byte concatenation absorbs
        # the second collector's startup into the first collector's close.
        self.assertNotIn('app', observer.parse((manager+installer).decode().splitlines())[1])
        self.assertEqual(observer.parse(host.trace_lines(manager, installer))[1], {'app'})
        with self.assertRaises(ValueError):
            observer.parse(host.trace_lines(manager, b'execve("private", [], 0x0) = 0'))

    def test_browser_failure_marker_survives_a_large_private_journal_tail(self):
        marker = b'offline-browser: failed at chromium-comment (Error); no passing report\n'
        private = b'private-fixture-credential\n' * 5000
        self.assertIsNone(evidence.browser_failure_diagnostic((marker+private)[-65536:].decode()))
        self.assertEqual(host.failure_detail('delivered-browser-workflows', marker+private), 'chromium-comment (Error)')
        self.assertIsNone(host.failure_detail('delivered-browser-workflows', private))

    def test_recovery_stage_and_budget_diagnostics_are_fixed_and_bounded(self):
        marker='offline-browser: failed at chromium-comment (Error); no passing report\n'
        records=[{'msg':'lifecycle verification rejected request','reason':'deadline-exceeded',
                  'stage':'database','verification_ms':10003,'verification_timeout_ms':10000,
                  'pool_acquired':4,'pool_total':4,'pool_max':4,'private':'credential'},
                 {'msg':'lifecycle verification rejected request','stage':'private-credential',
                  'verification_ms':10**50,'verification_timeout_ms':'private','pool_acquired':True,
                  'pool_total':4,'pool_max':4},
                 {'msg':'lifecycle verification rejected request','stage':['private-credential']}]
        detail=host.failure_detail('delivered-browser-workflows', (marker+'\n'.join(map(json.dumps,records))).encode())
        self.assertIn('verification-stage=database',detail)
        self.assertIn('verification-ms=10003..10003',detail)
        self.assertIn('verification-budget-ms=10000',detail)
        self.assertIn('pool-acquired=4/4',detail)
        self.assertNotIn('private',detail)
        self.assertNotIn('credential',detail)

    def test_node_security_minimum_matches_all_toolchain_selectors(self):
        pin = (ROOT / '.nvmrc').read_text().strip()
        self.assertEqual(tuple(map(int, pin.split('.'))), evidence.NODE_MIN_VERSION)
        expected = '>=' + pin + ' <' + str(evidence.NODE_MIN_VERSION[0] + 1)
        for name in ('package.json', 'web/package.json'):
            self.assertEqual(json.loads((ROOT / name).read_text())['engines']['node'], expected)
        self.assertEqual(json.loads((ROOT / 'web/package-lock.json').read_text())['packages']['']['engines']['node'], expected)

    def test_old_or_incompatible_browser_node_cannot_satisfy_acceptance(self):
        for version in ('v24.21.0', 'v24.22.0', 'v22.23.4', 'v26.12.1',
                        'v24.22.1-rc.1', '24.22.1', None, 24):
            report = copy.deepcopy(self.report)
            report['browser']['driver']['node'] = version
            with self.subTest(version=version), self.assertRaisesRegex(ValueError, 'refresh the test OS'):
                evidence.validate(report, self.bundle, 'd'*64, 'c'*64)
        for version in ('v24.22.1', 'v24.22.2', 'v24.23.0'):
            report = copy.deepcopy(self.report)
            report['browser']['driver']['node'] = version
            evidence.validate(report, self.bundle, 'd'*64, 'c'*64)

    def test_runtime_probe_cannot_be_requested_as_closeout_or_satisfy_it(self):
        with self.assertRaisesRegex(ValueError,'require --development'):
            host.main(SimpleNamespace(runtime_probe=True,development=False))
        previous={'release':{'revision':'9'*40,'image':'example.test/previous@sha256:'+'f'*64},'bundle_sha256':'e'*64}
        report=full_host_report(self.bundle,'d'*64,'c'*64,'ubuntu-24.04',previous)
        probe={key:report[key] for key in ('result','suite_sha256','profile','arch','release','bundle_sha256',
               'virtual_cpus','lifecycle_check_timeout_seconds','virtual_cpu','rootfs_sha256','kernel_sha256','archive_sha256')}
        probe.update(schema=1,suite='offline-runtime-probe-v1',coverage='runtime-probe',runtime=report['scenarios']['runtime'])
        evidence.validate_runtime_probe(probe,self.bundle,'d'*64,'c'*64)
        with self.assertRaises(ValueError):evidence.validate_closeout(probe,self.bundle,'d'*64,'c'*64)
        for key,value in (('coverage','closeout'),('release',{}),('suite_sha256','e'*64),('virtual_cpu','tcg')):
            with self.subTest(key=key),self.assertRaises(ValueError):
                evidence.validate_runtime_probe({**probe,key:value},self.bundle,'d'*64,'c'*64)
        broken=copy.deepcopy(probe)
        broken['runtime']['maintenance_timer_triggered']=False
        with self.assertRaises(ValueError):evidence.validate_runtime_probe(broken,self.bundle,'d'*64,'c'*64)

    def test_closeout_timing_budgets_must_match_actual_acceleration(self):
        previous={'release':{'revision':'9'*40,'image':'example.test/previous@sha256:'+'f'*64},'bundle_sha256':'e'*64}
        report=full_host_report(self.bundle,'d'*64,'c'*64,'ubuntu-24.04',previous)
        report['network']['control_interval_limit_seconds']=120
        with self.assertRaises(ValueError):
            evidence.validate_closeout(report,self.bundle,'d'*64,'c'*64)
        report['virtual_cpu']='tcg'
        report['scenarios']['runtime']['unit_file_bus_timeout_seconds']=180
        with self.assertRaises(ValueError):
            evidence.validate_closeout(report,self.bundle,'d'*64,'c'*64)
        report['browser']['driver']['timing_mode']='software-emulation'
        report['virtual_cpus']=4
        report['lifecycle_check_timeout_seconds']=10
        evidence.validate_closeout(report,self.bundle,'d'*64,'c'*64)
        report['browser']['driver']['recovery_read_retries']=2
        evidence.validate_closeout(report,self.bundle,'d'*64,'c'*64)
        report['virtual_cpu']='kvm'
        report['scenarios']['runtime']['unit_file_bus_timeout_seconds']=0
        report['virtual_cpus']=2
        report['lifecycle_check_timeout_seconds']=1
        report['network']['control_interval_limit_seconds']=20
        report['browser']['driver']['timing_mode']='standard'
        with self.assertRaises(ValueError):
            evidence.validate_closeout(report,self.bundle,'d'*64,'c'*64)
        report['virtual_cpu']='tcg'
        report['scenarios']['runtime']['unit_file_bus_timeout_seconds']=180
        report['virtual_cpus']=4
        report['lifecycle_check_timeout_seconds']=10
        report['browser']['driver']['timing_mode']='software-emulation'
        report['network']['control_interval_limit_seconds']=121
        with self.assertRaises(ValueError):
            evidence.validate_closeout(report,self.bundle,'d'*64,'c'*64)

    def test_public_control_reason_excludes_private_content(self):
        message = 'ValueError: Network negative control exceeded its bounded interval'
        self.assertEqual(evidence.control_failure_diagnostic('password=private\n'+message+'\nprivate journal'),
                         'control-window-timeout')
        self.assertIsNone(evidence.control_failure_diagnostic(message+' password=private'))
        self.assertIsNone(evidence.control_failure_diagnostic('ValueError: password=private'))

    def test_guest_cpu_count_must_match_acceleration(self):
        previous={'release':{'revision':'9'*40,'image':'example.test/previous@sha256:'+'f'*64},'bundle_sha256':'e'*64}
        report=full_host_report(self.bundle,'d'*64,'c'*64,'ubuntu-24.04',previous)
        for count in (None,True,'2',0,4):
            broken=copy.deepcopy(report)
            broken['virtual_cpus']=count
            with self.subTest(count=count),self.assertRaises(ValueError):
                evidence.validate_closeout(broken,self.bundle,'d'*64,'c'*64)
        report['virtual_cpu']='tcg'
        report['scenarios']['runtime']['unit_file_bus_timeout_seconds']=180
        report['browser']['driver']['timing_mode']='software-emulation'
        report['network']['control_interval_limit_seconds']=120
        with self.assertRaises(ValueError):
            evidence.validate_closeout(report,self.bundle,'d'*64,'c'*64)
        report['virtual_cpus']=4
        report['lifecycle_check_timeout_seconds']=10
        evidence.validate_closeout(report,self.bundle,'d'*64,'c'*64)

    def test_verification_timeout_must_match_real_acceleration(self):
        previous={'release':{'revision':'9'*40,'image':'example.test/previous@sha256:'+'f'*64},'bundle_sha256':'e'*64}
        report=full_host_report(self.bundle,'d'*64,'c'*64,'ubuntu-24.04',previous)
        for value in (None,True,'1',0,5,10):
            broken=copy.deepcopy(report)
            broken['lifecycle_check_timeout_seconds']=value
            with self.subTest(value=value),self.assertRaises(ValueError):
                evidence.validate_closeout(broken,self.bundle,'d'*64,'c'*64)
        report['virtual_cpu']='tcg'
        report['scenarios']['runtime']['unit_file_bus_timeout_seconds']=180
        report['virtual_cpus']=4
        report['browser']['driver']['timing_mode']='software-emulation'
        report['network']['control_interval_limit_seconds']=120
        with self.assertRaises(ValueError):
            evidence.validate_closeout(report,self.bundle,'d'*64,'c'*64)
        report['lifecycle_check_timeout_seconds']=10
        evidence.validate_closeout(report,self.bundle,'d'*64,'c'*64)

    def test_public_browser_failure_excludes_private_content_and_unknown_labels(self):
        private = 'password=private-fixture-value\n'
        marker = 'offline-browser: failed at firefox-login (TimeoutError); no passing report'
        self.assertEqual(evidence.browser_failure_diagnostic(private+marker+'\nprivate stack trace'),
                         'firefox-login (TimeoutError)')
        labels='\noffline-browser: reason wait-timeout\noffline-browser: matcher toBeVisible\noffline-browser: http-status 409\n'
        self.assertEqual(evidence.browser_failure_diagnostic(private+marker+labels),
                         'firefox-login (TimeoutError) reason=wait-timeout matcher=toBeVisible http=409')
        unknown='\noffline-browser: reason private-value\noffline-browser: matcher private-value\noffline-browser: http-status 409 private-value\n'
        self.assertEqual(evidence.browser_failure_diagnostic(marker+unknown),'firefox-login (TimeoutError)')
        for message in ('offline-browser: failed at private-fixture-value (Error); no passing report',
                        'offline-browser: failed at firefox-login (PrivatePassword); no passing report',
                        marker+' private-fixture-value'):
            with self.subTest(message=message):
                self.assertIsNone(evidence.browser_failure_diagnostic(message))

    def test_browser_failure_classifies_recovery_without_exposing_responses_or_journals(self):
        marker='offline-browser: failed at firefox-create-item-response (AssertionError); no passing report'
        records=[{'msg':'request','route':'unmatched','status':503,'duration_ms':1200,'private':'secret'},
                 {'msg':'request','route':'unmatched','status':503,'duration_ms':20},
                 {'msg':'request','route':'/api/v1/items','status':503,'duration_ms':1500},
                 {'msg':'request','route':'unmatched','status':503,'duration_ms':'private'},
                 {'msg':'private','route':'unmatched','status':503,'duration_ms':1500},
                 {'msg':'lifecycle verification rejected request','reason':'deadline-exceeded','private':'secret'},
                 {'msg':'lifecycle verification rejected request','reason':'secret'}]
        labels='\noffline-browser: unavailable POST-recovery\noffline-browser: unavailable GET-problem\n'
        labels+='offline-browser: unavailable POST-recovery private\noffline-browser: unavailable PRIVATE-other\n'
        journal='\n'.join('private-journal-prefix '+json.dumps(record) for record in records)
        self.assertEqual(evidence.browser_failure_diagnostic(marker+labels+journal),
                         'firefox-create-item-response (AssertionError) unavailable=GET-problem,POST-recovery recovery-late=1 recovery-early=1 recovery-timeouts=1')

    def setUp(self):
        self.bundle = {'arch':'amd64', 'release':{'revision':'a'*40, 'image':'example.test/sierx@sha256:'+'b'*64}}
        self.report = {**self.bundle, 'schema':evidence.SCHEMA, 'suite':evidence.SUITE, 'suite_sha256':'c'*64,
                       'bundle_sha256':'d'*64, 'result':'passed', 'profile':'ubuntu-24.04',
                       'checks':evidence.CHECKS, 'isolation':evidence.ISOLATION,'virtual_cpus':2,'lifecycle_check_timeout_seconds':1}
        self.report['coverage']='development'
        self.report['host_versions']={'kernel':'6.8.0-fixture','systemd':'systemd 255','podman':'podman version 4.9.3','selinux':'disabled'}
        self.report['browser'] = {'result':'passed', 'playwright':'1.63.0', 'browsers':[
            {'engine':engine, 'version':'1.0', 'checks':evidence.BROWSER_CHECKS, 'external_requests':0,
             'tls':'leaf-spki-pin' if engine=='chromium' else 'fixture-ca-nss',
             'service_workers':0, 'observer_controls':['document','document-ipv6','fetch','image','websocket']}
            for engine in ('chromium','firefox')]}
        self.report['browser']['driver']={'node':'v24.22.1','policy':'seccomp-deny-io-uring','policy_verified':True,'external_fetch_control':True,'ipv4_only_verified':True,'recovery_read_retries':0}

    def test_browser_read_recovery_count_is_required_and_bounded(self):
        for value in (-1,11,True,'1',None):
            report=copy.deepcopy(self.report)
            report['browser']['driver']['recovery_read_retries']=value
            with self.subTest(value=value),self.assertRaises(ValueError):
                evidence.validate(report,self.bundle,'d'*64,'c'*64)
        del self.report['browser']['driver']['recovery_read_retries']
        with self.assertRaises(ValueError):
            evidence.validate(self.report,self.bundle,'d'*64,'c'*64)

    def test_complete_report_is_bound_to_exact_fixture_and_native_candidate(self):
        evidence.validate(self.report, self.bundle, 'd'*64, 'c'*64)
        for field, value in (('schema', 0), ('suite','old'), ('suite_sha256','e'*64), ('arch','arm64'),
                             ('release',{}), ('bundle_sha256','e'*64), ('result','failed'),
                             ('checks',evidence.CHECKS[:-1]), ('profile','ubuntu-22.04')):
            with self.subTest(field=field), self.assertRaises(ValueError):
                evidence.validate({**self.report,field:value}, self.bundle, 'd'*64, 'c'*64)

    def test_mocked_manager_host_network_or_privileged_runtime_cannot_pass(self):
        for key, value in (('network','host'), ('rootless',False), ('fresh_image_store',False),
                           ('user_manager','mock'), ('system_manager','host'),('storage_driver','vfs'),('rootless_network','pasta')):
            report = copy.deepcopy(self.report)
            report['isolation'][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                evidence.validate(report,self.bundle,'d'*64,'c'*64)

    def test_browser_coverage_and_controls_are_required(self):
        for field,value in (('browsers',[]),('result','failed'),('playwright','')):
            report=copy.deepcopy(self.report)
            report['browser'][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):
                evidence.validate(report,self.bundle,'d'*64,'c'*64)
        for field,value in (('checks',[]),('external_requests',1),('observer_controls',[]),('service_workers',1)):
            report=copy.deepcopy(self.report)
            report['browser']['browsers'][1][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):
                evidence.validate(report,self.bundle,'d'*64,'c'*64)
        report=copy.deepcopy(self.report)
        report['browser']['driver']['ipv4_only_verified']=False
        with self.assertRaises(ValueError):evidence.validate(report,self.bundle,'d'*64,'c'*64)

    def test_complete_closeout_requires_every_real_scenario_and_observer(self):
        previous={'release':{'revision':'9'*40,'image':'example.test/previous@sha256:'+'f'*64},'bundle_sha256':'e'*64}
        report=full_host_report(self.bundle,'d'*64,'c'*64,'ubuntu-24.04',previous)
        evidence.validate_closeout(report,self.bundle,'d'*64,'c'*64)
        for name in report['scenarios']:
            broken=copy.deepcopy(report)
            del broken['scenarios'][name]
            with self.subTest(name=name),self.assertRaises(ValueError):
                evidence.validate_closeout(broken,self.bundle,'d'*64,'c'*64)
        for name in ('network','rootfs_sha256','kernel_sha256'):
            broken=copy.deepcopy(report)
            del broken[name]
            with self.subTest(name=name),self.assertRaises(ValueError):
                evidence.validate_closeout(broken,self.bundle,'d'*64,'c'*64)
        for scenario,key,value in (('two_release','previous',self.bundle['release']),
                ('two_release','schema_after',16),('failed_health','candidate_started',False),
                ('runtime','elapsed_seconds',1),('runtime','maintenance_timer_triggered',False),
                ('acquisition','https_verified',False)):
            broken=copy.deepcopy(report)
            broken['scenarios'][scenario][key]=value
            with self.subTest(scenario=scenario,key=key),self.assertRaises(ValueError):
                evidence.validate_closeout(broken,self.bundle,'d'*64,'c'*64)

    def test_development_or_incomplete_network_reports_never_satisfy_promotion(self):
        with self.assertRaises(ValueError):evidence.validate_closeout(self.report,self.bundle,'d'*64,'c'*64)
        previous={'release':{'revision':'9'*40,'image':'example.test/previous@sha256:'+'f'*64},'bundle_sha256':'e'*64}
        report=full_host_report(self.bundle,'d'*64,'c'*64,'ubuntu-24.04',previous)
        for key,value in (('negative_controls',{}),('external_attempts',1),('processes',[]),('attempts_examined',0),('blocked_ipv6_sockets',0),('kernel_control_truncations',-1),('kernel_control_truncations',True)):
            broken=copy.deepcopy(report)
            broken['network'][key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):
                evidence.validate_closeout(broken,self.bundle,'d'*64,'c'*64)


class PreparedOSTests(unittest.TestCase):
    def test_vm_has_no_network_device_forwarding_or_operator_bus(self):
        for arch in ('amd64','arm64'):
            command=host.qemu_command(arch,'tcg',Path('/fixture/disk'),Path('/fixture/kernel'),Path('/fixture/initrd'),Path('/fixture/serial'))
            self.assertEqual(command[command.index('-nic')+1],'none')
            self.assertIn('-nodefaults',command)
            self.assertEqual(command[command.index('-smp')+1],'4')
            native=host.qemu_command(arch,'kvm',Path('/fixture/disk'),Path('/fixture/kernel'),Path('/fixture/initrd'),Path('/fixture/serial'))
            self.assertEqual(native[native.index('-smp')+1],'2')
            self.assertNotIn('-netdev',command)
            self.assertIn('console='+('ttyS0' if arch=='amd64' else 'ttyAMA0'),command[-1])
            self.assertFalse(any('hostfwd' in field or '/run/user/' in field or 'virtfs' in field for field in command))

    def archive(self, folder, names, symlink=None):
        path = Path(folder) / 'os.tar'
        with tarfile.open(path,'w') as stream:
            if symlink:
                entry=tarfile.TarInfo(symlink)
                entry.type=tarfile.SYMTYPE
                entry.linkname='/tmp'
                stream.addfile(entry)
            for name in names:
                entry=tarfile.TarInfo(name)
                entry.size=2
                stream.addfile(entry,io.BytesIO(b'os'))
        return path,hashlib.sha256(path.read_bytes()).hexdigest()

    def test_checksum_and_member_paths_are_checked_before_extraction(self):
        with tempfile.TemporaryDirectory() as folder:
            path,digest=self.archive(folder,['etc/os-release'])
            host.verify_rootfs(str(path),digest)
            with self.assertRaises(ValueError):host.verify_rootfs(path,'0'*64)
            for name in ('../escape','/absolute'):
                path,digest=self.archive(folder,[name])
                with self.subTest(name=name),self.assertRaises(ValueError):host.verify_rootfs(path,digest)

    def test_symlink_parent_cannot_redirect_archive_writes_outside_guest(self):
        with tempfile.TemporaryDirectory() as folder:
            path,digest=self.archive(folder,['redirect/escape'],symlink='redirect')
            with self.assertRaises(ValueError):host.verify_rootfs(path,digest)

    def test_hard_link_cannot_read_through_an_absolute_guest_symlink(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'os.tar'
            with tarfile.open(path,'w') as stream:
                link=tarfile.TarInfo('redirect')
                link.type=tarfile.SYMTYPE
                link.linkname='/tmp'
                stream.addfile(link)
                hard=tarfile.TarInfo('hard')
                hard.type=tarfile.LNKTYPE
                hard.linkname='redirect/outside'
                stream.addfile(hard)
            with self.assertRaises(ValueError):host.verify_rootfs(path,hashlib.sha256(path.read_bytes()).hexdigest())


if __name__ == '__main__':
    unittest.main()
