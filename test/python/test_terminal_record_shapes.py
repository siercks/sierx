"""Terminal rendering never substitutes for complete kernel non-execution proof."""
import unittest

from test_kernel_network_evidence import proof
from test_kernel_terminal_ledger import traffic
import network_observer as observer


class TerminalRecordShapeTests(unittest.TestCase):
    def test_failure_shape_is_a_fixed_category_without_trace_content(self):
        self.assertEqual(observer.safe_failure_fields({'terminal_record':'private arguments'}), {})
        metadata, events, lines = traffic()
        events += ['task-10 [000] .... 101.010000: sys_sendmsg -> 0xffffffffffffffda']
        for rendered in self.shapes(lines):
            with self.assertRaises(observer.NetworkObservationError) as caught:
                observer.parse(rendered, kernel=proof(metadata, events))
            self.assertEqual(caught.exception.observer_details['terminal_record'], 'pseudo-return')

    def shapes(self, lines):
        prefix = lines[-1].removesuffix(' <unfinished ...>')
        return ([lines[0], prefix + ') = ?'],
                [lines[0], lines[-1], '10<firefox> 1101.100000 <... sendmsg resumed>) = ?'])

    def test_real_tracer_pseudo_return_requires_the_same_complete_ledger(self):
        metadata, events, lines = traffic()
        for rendered in self.shapes(lines):
            with self.subTest(rendered=rendered):
                stats = {}
                self.assertEqual(observer.parse(rendered, stats, proof(metadata, events))[0], [])
                self.assertEqual(stats['cancelled_after_verified_ledger']['firefox'], 1)
                with self.assertRaises(observer.NetworkObservationError):
                    observer.parse(rendered)

    def test_resumed_terminal_retains_entry_time_and_arguments(self):
        _, _, lines = traffic()
        rendered = self.shapes(lines)[1]
        terminal = set()
        decoded = observer.records(rendered, terminal)
        self.assertEqual(decoded[-1], ('10', 'firefox', 1101.0,
            'sendmsg(60, 0x1234, MSG_NOSIGNAL) = ?'))
        self.assertEqual(terminal, {('10', 'sendmsg', 1101.0)})

    def test_restart_unavailable_and_malformed_unknown_results_stay_rejected(self):
        metadata, events, lines = traffic()
        for suffix in ('? ERESTARTSYS (To be restarted if SA_RESTART is set)',
                       '? <unavailable>', '? (INJECTED)', '??', '? extra', ''):
            for rendered in self.shapes(lines):
                changed = [*rendered[:-1], rendered[-1].removesuffix('?') + suffix]
                with self.subTest(suffix=suffix), self.assertRaises(observer.NetworkObservationError):
                    observer.parse(changed, kernel=proof(metadata, events))

    def test_missing_extra_or_orphan_kernel_history_stays_rejected_for_both_shapes(self):
        metadata, events, lines = traffic()
        for changed in (events[:-1], events[:-2], events + [events[-1]],
                        events + ['task-10 [000] .... 101.010000: sys_sendmsg -> 0xffffffffffffffda'],
                        events + ['task-10 [000] .... 101.010000: sys_sendmsg(fd: 0x3c, msg: 0x1234, flags: 0)']):
            for rendered in self.shapes(lines):
                with self.subTest(changed=changed), self.assertRaises(observer.NetworkObservationError):
                    observer.parse(rendered, kernel=proof(metadata, changed))

    def test_earlier_unknown_or_executed_opaque_calls_are_never_hidden(self):
        metadata, events, lines = traffic()
        for rendered in self.shapes(lines):
            for prior in (lines[0].replace(' = 5', ' = ?'),
                          lines[0].replace('5<UNIX:[12]>', '5')):
                with self.subTest(prior=prior), self.assertRaises(observer.NetworkObservationError):
                    observer.parse([prior, *rendered[1:]], kernel=proof(metadata, events))

    def test_external_terminal_destinations_remain_attempts(self):
        metadata, events, lines = traffic()
        terminal = ('10<firefox> 1101.000000 connect(60, {sa_family=AF_INET, '
                    'sin_port=htons(443), sin_addr=inet_addr("198.51.100.99")}, 16) = ?')
        stats = {}
        attempts, _ = observer.parse([lines[0], terminal], stats, proof(metadata, events))
        self.assertEqual([(a.address, a.port) for a in attempts], [('198.51.100.99', 443)])
        self.assertEqual(sum(stats['cancelled_before_kernel_entry'].values()), 0)


if __name__ == '__main__':
    unittest.main()
