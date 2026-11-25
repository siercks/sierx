"""Run only the disposable tracer diagnostic and publish its safe envelope."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from tracer_diagnostic import architecture, state_directory, target_user, verify_result, safe_probe_progress

root = state_directory()
revision = os.environ['SIERX_DIAGNOSTIC_REVISION']
if not re.fullmatch(r'[a-f0-9]{40}',revision): raise SystemExit('Invalid diagnostic revision')
report = root.parent/('tracer-termination-diagnostic-'+architecture()+'.json')
stage = 'verify-inputs'
envelope = {'schema':1,'suite':'tracer-termination-diagnostic-v1','revision':revision,
            'arch':architecture(),'result':'failed','release_acceptance':False,
            'historical_cause_proven':False}
try:
    if os.getuid() != 0: raise ValueError('Root diagnostic namespace required')
    if os.environ['SIERX_DIAGNOSTIC_ARCH'] != architecture():
        raise ValueError('Requested architecture differs from the native diagnostic')
    build = json.loads((root/'build.json').read_text())
    target_user(build)
    for name in ('control','natural'):
        stage = name
        with (root/(name+'.private.log')).open('wb') as private:
            subprocess.run([sys.executable,'-B',str(Path(__file__).with_name('diagnostic-tracer-'+name+'.py'))],
                           stdout=private,stderr=subprocess.STDOUT,check=True,timeout=210)
    stage = 'validate-evidence'
    controlled = json.loads((root/'phase3-getsiginfo-control.json').read_text())
    natural = json.loads((root/'phase3-getsiginfo-natural.json').read_text())
    envelope = verify_result(build,controlled,natural,revision)
except (ValueError,OSError,KeyError,TypeError,AssertionError,subprocess.SubprocessError) as error:
    envelope['failure_stage'] = stage
    envelope['failure_type'] = type(error).__name__
    if stage in {'control','natural','validate-evidence'}:
        name = 'natural' if stage=='validate-evidence' else stage
        progress = safe_probe_progress(root/(name+'.private.log'))
        if progress is not None:envelope['last_probe_case'] = progress
finally:
    report.write_text(json.dumps(envelope,indent=2)+'\n')
    report.chmod(0o644)
raise SystemExit(0 if envelope['result']=='passed' else 1)
