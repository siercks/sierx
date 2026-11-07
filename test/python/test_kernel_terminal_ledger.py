"""Prior traffic never substitutes for an exact, complete execution ledger."""
import unittest

from test_kernel_network_evidence import fixture, proof
import network_observer as observer


def traffic():
    metadata, events = fixture()
    events += ['task-10 [000] .... 100.901000: sys_sendto(fd: 0x5, buff: 0x9999, len: 5)',
               'task-10 [000] .... 100.902000: sys_sendto -> 0x5']
    lines = ['10<firefox> 1100.900000 sendto(5<UNIX:[12]>, "probe", 5, 0, NULL, 0) = 5',
             '10<firefox> 1101.000000 sendmsg(60, 0x1234, MSG_NOSIGNAL <unfinished ...>']
    return metadata, events, lines


class TerminalLedgerTests(unittest.TestCase):
    def test_ledger_diagnostics_publish_only_bounded_counts_and_fixed_categories(self):
        for status in ('private payload',{'private':'payload'},['private'],True):
            self.assertEqual(observer.safe_failure_fields({'kernel':{'ledger_status':status,
                'trace_network_records':-1,'matched_prior_calls':True,'payload':'private'}}),{})
        self.assertEqual(observer.safe_failure_fields({'kernel':{'ledger_status':'call-mismatch',
            'trace_network_records':34,'matched_prior_calls':12,'payload':'private'}}),
            {'kernel':{'ledger_status':'call-mismatch','trace_network_records':34,'matched_prior_calls':12}})

    def test_prior_completed_calls_need_full_accounting_before_terminal_non_execution(self):
        metadata, events, lines = traffic()
        evidence = proof(metadata, events)
        # The original lifetime-only criterion remains strict.
        self.assertFalse(evidence.cancelled_before_entry(10, 1101.0))
        stats = {}
        self.assertEqual(observer.parse(lines, stats, evidence)[0], [])
        self.assertEqual(stats['cancelled_after_verified_ledger']['firefox'], 1)
        self.assertEqual(stats['cancelled_before_kernel_entry']['firefox'], 1)

    def test_missing_extra_mismatched_or_out_of_order_kernel_calls_are_never_excused(self):
        metadata, events, lines = traffic()
        for changed in (
            events[:-1], events[:-2], events + [events[-2]], events + [events[-1]],
            [s.replace('fd: 0x5,', 'fd: 0x6,') for s in events],
            [s.replace('100.902000: sys_sendto -> 0x5', '100.902000: sys_sendto -> 0x6') for s in events],
            [s.replace('100.901000: sys_sendto', '100.901000: sys_sendmsg') for s in events],
            [s.replace('100.902000:', '100.899000:') for s in events],
            [s.replace('100.901000:', '101.001000:').replace('100.902000:', '101.002000:') for s in events],
            events + ['task-10 [000] .... 101.001000: sys_sendmsg(fd: 0x3c, msg: 0x1234, flags: 0)'],
            events + ['task-10 [000] .... 103.000000: sched_process_exit: comm=reused pid=10 prio=120'],
        ):
            with self.subTest(changed=changed), self.assertRaises(observer.NetworkObservationError):
                observer.parse(lines, kernel=proof(metadata, changed))

    def test_missing_duplicate_wrong_or_unfinished_process_records_are_never_excused(self):
        metadata, events, lines = traffic()
        for changed in (
            lines[1:], lines[:1] + lines,
            [lines[0].replace(' = 5', ' = 4'), lines[1]],
            [lines[0].replace('1100.900000', '1101.100000'), lines[1]],
            [lines[0].replace(' = 5', ' = ? ERESTARTSYS'), lines[1]],
            [lines[0].replace(' = 5', ' <unfinished ...>'), lines[1]],
            [lines[0].replace(' = 5', ' = -1 UNKNOWN_ERROR'), lines[1]],
            lines + ['10<firefox> 1101.100000 sendto(5<UNIX:[12]>, "probe", 5, 0, NULL, 0) = 5'],
        ):
            with self.subTest(changed=changed), self.assertRaises((observer.NetworkObservationError, ValueError)):
                observer.parse(changed, kernel=proof(metadata, events))

    def test_kernel_errno_and_each_completed_call_must_match(self):
        metadata, events, lines = traffic()
        events += ['task-10 [000] .... 100.951000: sys_connect(fd: 0x6, uservaddr: 0x1234, addrlen: 16)',
                   'task-10 [000] .... 100.952000: sys_connect -> 0xffffffffffffff91']
        local = '10<firefox> 1100.950000 connect(6, {sa_family=AF_UNIX, sun_path="fixture"}, 16) = -1 ECONNREFUSED'
        self.assertEqual(observer.parse([lines[0], local, lines[1]], kernel=proof(metadata, events))[0], [])
        with self.assertRaises(observer.NetworkObservationError):
            observer.parse([lines[0], local.replace('ECONNREFUSED', 'EPERM'), lines[1]], kernel=proof(metadata, events))

    def test_resumed_calls_are_accounted_and_executed_opaque_calls_still_fail(self):
        metadata, events, lines = traffic()
        resumed = [lines[0].replace(' = 5', ' <unfinished ...>'),
                   '10<firefox> 1100.903000 <... sendto resumed>) = 5', lines[1]]
        self.assertEqual(observer.parse(resumed, kernel=proof(metadata, events))[0], [])
        with self.assertRaises(observer.NetworkObservationError):
            observer.parse([lines[0].replace('5<UNIX:[12]>', '5'), lines[1]], kernel=proof(metadata, events))

    def test_explicit_external_calls_remain_attempts_and_batched_terminal_is_rejected(self):
        metadata, events, lines = traffic()
        external = lines[0].replace('5<UNIX:[12]>', '5').replace('NULL, 0',
            '{sa_family=AF_INET, sin_port=htons(443), sin_addr=inet_addr("198.51.100.99")}, 16')
        attempts, _ = observer.parse([external, lines[1]], kernel=proof(metadata, events))
        self.assertEqual([(a.address, a.port) for a in attempts], [('198.51.100.99', 443)])
        terminal = '10<firefox> 1101.000000 sendmmsg(60, [{msg_hdr={msg_name=NULL}}], 1, 0 <unfinished ...>'
        with self.assertRaises(observer.NetworkObservationError):
            observer.parse([lines[0], terminal], kernel=proof(metadata, events))

    def test_clock_overlap_missing_exit_and_orphan_return_remain_rejected(self):
        metadata, events, lines = traffic()
        for changed in (
            [s.replace('100.902000:', '100.999500:') for s in events],
            [s for s in events if 'pid=10' not in s],
            events + ['task-10 [000] .... 101.010000: sys_sendmsg -> 0xffffffffffffffda'],
        ):
            with self.subTest(changed=changed), self.assertRaises(observer.NetworkObservationError):
                observer.parse(lines, kernel=proof(metadata, changed))


if __name__ == '__main__':
    unittest.main()
