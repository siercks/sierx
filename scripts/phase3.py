"""Phase 3 entry checks and fail-closed acceptance scaffolding (ADR-031).

No feature evidence is synthesized here. P3-33 must attach the real test,
reference-hardware and owner/device records before gate-3 can turn green.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys


SCENARIOS = (
    'board-parity', 'wip', 'workflow', 'ranks', 'recovery', 'accessibility',
    'mobile', 'preferences', 'dates', 'density', 'identity', 'security',
    'avatar', 'personal-views', 'sso-preparation', 'delivery',
)


def validate_evidence(report, revision):
    if report.get('revision') != revision:
        raise ValueError('Phase 3 acceptance evidence is not for this commit')
    checks = report.get('checks', {})
    for name in SCENARIOS:
        check = checks.get(name, {})
        if check.get('result') != 'passed' or not check.get('evidence'):
            raise ValueError(f'Missing passing Phase 3 evidence: {name}')
    for name in ('reference_hardware', 'iphone_safari', 'owner_review'):
        if not isinstance(report.get(name), str) or not report[name].strip():
            raise ValueError(f'Missing Phase 3 record: {name}')
    benchmark = report.get('board_benchmark', {})
    for key in ('fixture', 'request_scope', 'sampling', 'first_load', 'additional_page'):
        if not benchmark.get(key):
            raise ValueError(f'Missing board benchmark record: {key}')
    if benchmark.get('item_count') != 500:
        raise ValueError('Board benchmark must use the documented 500-item fixture')
    p95 = benchmark.get('server_p95_ms')
    if isinstance(p95, bool) or not isinstance(p95, (int, float)) or not 0 < p95 < 150:
        raise ValueError('Board server p95 must be below 150 ms')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('acceptance',))
    parser.add_argument('--evidence', type=Path, default=Path('dist/phase3-acceptance.json'))
    args = parser.parse_args()
    if not args.evidence.is_file():
        raise ValueError('Phase 3 acceptance is incomplete: no candidate-bound evidence report. '
                         'See docs/PHASE-3-ACCEPTANCE.md; gate-2 remains the source release gate.')
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
    validate_evidence(json.loads(args.evidence.read_text(encoding='utf-8')), revision)
    # Reports cannot certify absent production routes.
    source = Path('web/src/routes/table.ts').read_text(encoding='utf-8')
    for route in ('/board', '/account', '/account/appearance', '/account/preferences',
                  '/account/security', '/account/work', '/account/activity'):
        if f"path: '{route}'" not in source:
            raise ValueError(f'Phase 3 route is not implemented: {route}')
    print('gate-3: Phase 3 evidence present (retain underlying test and human records)')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(f'gate-3: {exc}', file=sys.stderr)
        sys.exit(1)
