"""Create the first real backlog item only after owner acceptance."""
import importlib.util
import json
import os
import pathlib
import sys
spec=importlib.util.spec_from_file_location('smoke',pathlib.Path(__file__).with_name('release-smoke.py'))
smoke=importlib.util.module_from_spec(spec);spec.loader.exec_module(smoke)

if __name__=='__main__':
    try:
        if os.environ.get('SIERX_CUTOVER_ACCEPTED')!='1':
            raise ValueError('Complete the durable-deployment checklist first')
        call=smoke.client()
        _,data=call('/api/v1/items?fields=id,key&limit=1')
        if json.loads(data)['data']:
            raise ValueError('Real backlog must be empty; do not import trial or benchmark fixtures')
        _,data=call('/api/v1/items',{'project':'SRX','type':'story','title':'Build Phase 3 from real use','body':'Use this backlog for development. Record Phase 2 walkthrough issues and seven consecutive days of primary-backlog use before starting Phase 3. Review the Phase 3 BUILD tasks against what actual use teaches us.'})
        item=json.loads(data)
        if item['key']!='SRX-1':
            raise ValueError('Created item is not SRX-1; inspect prior sequence use before cutover')
        call('/api/v1/auth/logout',{})
        print('cutover: SRX-1 created; begin the daily-use record when this becomes the primary backlog')
    except Exception:
        sys.exit('cutover: acceptance/input/API check failed; inspect the private host and do not repeat blindly')
