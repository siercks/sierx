"""Causal guest diagnostics must not broaden evidence or retry an import."""
import copy,importlib.util,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts'))
import native_tracer_diagnostic as diagnostic
spec=importlib.util.spec_from_file_location('guest_causal',ROOT/'scripts/diagnostic-guest-import-compare.py')
guest=importlib.util.module_from_spec(spec);spec.loader.exec_module(guest)


def build():
    return {'arch':'arm64','owner_uid':1001,'source_archive_sha256':diagnostic.ARCHIVE_SHA256,
        'patch_sha256':diagnostic.PATCH_SHA256,'observation_sha256':diagnostic.OBSERVATION_SHA256,
        'configure_flags':diagnostic.CONFIGURE_FLAGS,'release_acceptance':False,
        'builds':{mode:{'version':'6.8','sha256':letter*64,'base_source_sha256':diagnostic.SOURCE_SHA256[mode],
            'observed_source_sha256':diagnostic.OBSERVED_SOURCE_SHA256[mode]} for mode,letter in (('old','a'),('fixed','b'))}}


def case(mode='old',failure=False):
    roles={role:{'task_exited':True,'requested_exit_code':0} for role in ('installer','tracer','import-helper')}
    if failure:
        roles={'installer':{'task_exited':True},'import-helper':{'task_exited':True},
               'tracer':{'task_exited':True,'requested_exit_code':1}}
    return {'mode':mode,'suite':'offline-native-import-probe-v1','release_acceptance':False,
        'result':'failed' if failure else 'passed','tracer_returncode':int(failure),
        'strace_sha256':build()['builds'][mode]['sha256'],'podman_sha256':'c'*64,'kernel_release':'6.8.0-public',
        'fresh_rootless_overlay':True,'loopback_only':True,'installer_trace_mode':'ordinary-ptrace',
        'observation':{'kernel_exit_capture':'observed','kernel_exit':roles,
            'tracer_syscall_errors':[{'call':'ptrace','errno':3,'age_ms':5},{'call':'ptrace','errno':5,'age_ms':4}]
                if failure else [],'import_stage':'load-app' if failure else 'import-complete'},
        'query_observation':{'capture':'observed','failed_queries':int(failure),'esrch_queries':int(failure),
            'listen_eio':int(failure),'unique_same_target_pair':failure}}


def report(cause=False):
    return {'suite':'offline-native-tracer-comparison-v1','release_acceptance':False,'historical_cause_proven':False,
        'arch':'arm64','release':{'revision':'d'*40,'image':'local:fixture'},'bundle_sha256':'e'*64,
        'build':diagnostic.public_build(build()),'result':'cause-reproduced-and-corrected' if cause else 'inconclusive',
        'cases':[case(failure=True),case('fixed')] if cause else [case()],
        'parent_system_binary_unchanged':True}


class GuestTracerComparisonTests(unittest.TestCase):
    def validate(self,value):
        return guest.checked_comparison(value,build(),report()['release'],'e'*64)

    def test_inconclusive_stops_before_fixed_and_cannot_be_promoted(self):
        self.assertEqual(self.validate(report())['result'],'inconclusive')
        for key in ('release_acceptance','historical_cause_proven'):
            value=report();value[key]=True
            with self.subTest(key=key),self.assertRaises(ValueError):self.validate(value)
        value=report();value['cases'].append(case('fixed'))
        with self.assertRaises(ValueError):self.validate(value)

    def test_causal_verdict_requires_both_real_complete_cases_and_unchanged_parent(self):
        self.assertEqual(self.validate(report(True))['result'],'cause-reproduced-and-corrected')
        for fault in ('old-pass','fixed-failure','lost','missing-task','changed-binary','parent-changed'):
            value=report(True)
            if fault=='old-pass':value['cases'][0]=case()
            elif fault=='fixed-failure':value['cases'][1]['tracer_returncode']=1
            elif fault=='lost':value['cases'][0]['observation']['kernel_exit_capture']='lost-events'
            elif fault=='missing-task':value['cases'][1]['observation']['kernel_exit'].pop('installer')
            elif fault=='changed-binary':value['cases'][0]['strace_sha256']='f'*64
            else:value['parent_system_binary_unchanged']=False
            with self.subTest(fault=fault),self.assertRaises(ValueError):self.validate(value)

    def test_unknown_private_fields_are_rejected_before_publication(self):
        for fault in ('outer','case','observation','query'):
            value=report()
            target={'outer':value,'case':value['cases'][0],'observation':value['cases'][0]['observation'],
                    'query':value['cases'][0]['query_observation']}[fault]
            target['private']='credential'
            with self.subTest(fault=fault),self.assertRaises(ValueError):self.validate(value)

    def test_guest_configuration_keeps_tracee_sources_readable_and_state_private(self):
        host=guest.load('test_guest_setup','offline-host.py')
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)/'root';root.mkdir()
            for directory in ('etc','usr/sbin','var/log','opt','boot'):(root/directory).mkdir(parents=True,exist_ok=True)
            state=Path(temporary)/'state';state.mkdir()
            for mode in ('old','fixed'):(state/('strace-query-'+mode)).write_text(mode)
            # These are controlled setup inputs; no subprocess, network or boot.
            with patch.object(guest.offline,'digest',side_effect=lambda path:('a' if path.name.endswith('old') else 'b')*64), \
                    patch.object(host.os,'chown'),patch.object(guest,'ROOT',ROOT):
                guest.configure(root,host,{'suite_sha256':'1'*64,'bundle_sha256':'e'*64},build(),source_state=state)
            target=root/'opt/causal'
            self.assertEqual((target/'scripts/offline-native-import.py').stat().st_mode&0o777,0o644)
            self.assertEqual((target/'scripts').stat().st_mode&0o777,0o755)
            self.assertEqual((target/'dist').stat().st_mode&0o777,0o700)
            self.assertEqual((target/'dist/tracer-race-arm64/query-build.json').stat().st_mode&0o777,0o600)
            self.assertEqual((target/'dist/tracer-race-arm64/query-build.json').read_text().count('"owner_uid": 1001'),1)
            unit=(root/'etc/systemd/system/sierx-tracer-compare.service').read_text()
            self.assertIn('TimeoutStartSec=10700',unit);self.assertNotIn('sierx-trace-installer',unit)
