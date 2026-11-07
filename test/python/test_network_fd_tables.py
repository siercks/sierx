"""Descriptor table splits must preserve peers without inventing socket families."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
import network_observer as observer


def base():
    return ['10<chromium> 1.000000 socketpair(AF_UNIX, SOCK_STREAM, 0, [60, 61]) = 0',
            '10<chromium> 1.000001 clone(child_stack=NULL, flags=CLONE_FILES|SIGCHLD) = 11']


def send(pid,time='1.000005',fd=60):
    return f'{pid}<chromium> {time} sendto({fd}, "fixture", 7, 0, NULL, 0) = 7'


class DescriptorTableTests(unittest.TestCase):
    def test_successful_split_preserves_the_other_process_for_child_and_original_owner(self):
        for splitter,peer in ((10,11),(11,10)):
            for operation in ('unshare(CLONE_FILES)','execve("/usr/bin/chromium", ["fixture"], 0x0)',
                              'close_range(62, 62, CLOSE_RANGE_UNSHARE)'):
                with self.subTest(splitter=splitter,operation=operation):
                    lines=base()+[f'{splitter}<chromium> 1.000002 {operation} = 0',
                        f'{splitter}<chromium> 1.000003 close(60) = 0',send(peer)]
                    self.assertEqual(observer.parse(lines)[0],[])

    def test_failed_unshare_and_non_file_flags_leave_the_table_shared(self):
        for operation,result in (('unshare(CLONE_FILES)','-1 EPERM'),('unshare(CLONE_FS)','0'),
                                  ('execve("/missing", [], 0x0)','-1 ENOENT')):
            with self.subTest(operation=operation),self.assertRaises(observer.NetworkObservationError):
                observer.parse(base()+[f'11<chromium> 1.000002 {operation} = {result}',
                    '11<chromium> 1.000003 close(60) = 0',send(10)])

    def test_repeated_original_owner_splits_keep_each_peer_generation_distinct(self):
        lines=base()+['10<chromium> 1.000002 unshare(CLONE_FILES) = 0',
            '10<chromium> 1.000003 clone(child_stack=NULL, flags=CLONE_FILES|SIGCHLD) = 12',
            '10<chromium> 1.000004 unshare(CLONE_FILES) = 0',
            '10<chromium> 1.000005 close(60) = 0']
        self.assertEqual(observer.parse(lines+[send(11,'1.000006'),send(12,'1.000007')])[0],[])
        with self.assertRaises(observer.NetworkObservationError):observer.parse(lines+[send(10,'1.000008')])

    def test_dup_and_fcntl_preserve_exact_close_on_exec_rules(self):
        prefix=['10<chromium> 1.000000 socketpair(AF_UNIX, SOCK_STREAM, 0, [60, 61]) = 0',
            '10<chromium> 1.000001 fcntl(60, F_SETFD, FD_CLOEXEC) = 0',
            '10<chromium> 1.000002 dup(60) = 62',
            '10<chromium> 1.000003 dup3(60, 63, O_CLOEXEC) = 63',
            '10<chromium> 1.000004 fcntl(60, F_DUPFD_CLOEXEC, 64) = 64',
            '10<chromium> 1.000005 dup2(60, 60) = 60',
            '10<chromium> 1.000006 execve("/usr/bin/chromium", [], 0x0) = 0']
        self.assertEqual(observer.parse(prefix+[send(10,'1.000007',62)])[0],[])
        for fd in (60,63,64):
            with self.subTest(fd=fd),self.assertRaises(observer.NetworkObservationError):
                observer.parse(prefix+[send(10,'1.000007',fd)])
        cleared=prefix[:2]+['10<chromium> 1.000002 fcntl(60, F_SETFD, 0) = 0',prefix[-1]]
        self.assertEqual(observer.parse(cleared+[send(10,'1.000007')])[0],[])

    def test_unreadable_table_mutations_and_unknown_successful_bulk_flags_fail_closed(self):
        for line in ('unshare(CLONE_FILES) = 0','close_range(60, 61, 0) = 0'):
            with self.subTest(line=line),self.assertRaises(ValueError):observer.parse([line])
        for arguments in ('60, 61, FUTURE_UNKNOWN_FLAG','62, 60, 0','private, 61, 0'):
            with self.subTest(arguments=arguments),self.assertRaises(ValueError):
                observer.parse(base()+['11<chromium> 1.000002 close_range('+arguments+') = 0'])

    def test_bulk_close_removes_only_successfully_closed_descriptors(self):
        for flags in ('0','CLOSE_RANGE_UNSHARE'):
            with self.subTest(flags=flags),self.assertRaises(observer.NetworkObservationError):
                observer.parse(base()+[f'11<chromium> 1.000002 close_range(60, 4294967295, {flags}) = 0',send(11)])
        self.assertEqual(observer.parse(base()+['11<chromium> 1.000002 close_range(60, 61, 0) = -1 EINVAL',send(10)])[0],[])

    def test_cloexec_marks_without_closing_until_successful_exec(self):
        prefix=base()+['11<chromium> 1.000002 close_range(60, 60, CLOSE_RANGE_UNSHARE|CLOSE_RANGE_CLOEXEC) = 0']
        self.assertEqual(observer.parse(prefix+[send(11,'1.000003')])[0],[])
        ending=['11<chromium> 1.000004 execve("/usr/bin/chromium", [], 0x0) = 0',send(11)]
        with self.assertRaises(observer.NetworkObservationError):observer.parse(prefix+ending)
        self.assertEqual(observer.parse(prefix+ending[:-1]+[send(10)])[0],[])

    def test_socket_and_received_descriptor_cloexec_is_not_inherited_through_exec(self):
        for create in ('socket(AF_UNIX, SOCK_STREAM|SOCK_CLOEXEC, 0) = 60',
                       'socketpair(AF_UNIX, SOCK_STREAM|SOCK_CLOEXEC, 0, [60, 61]) = 0',
                       'recvmsg(9, {msg_control=[{cmsg_level=SOL_SOCKET, cmsg_type=SCM_RIGHTS, cmsg_data=[60<UNIX:[1]>]}], msg_flags=0}, MSG_CMSG_CLOEXEC) = 1'):
            with self.subTest(create=create),self.assertRaises(observer.NetworkObservationError):
                observer.parse(['10<chromium> 1.000000 '+create,
                    '10<chromium> 1.000001 execve("/usr/bin/chromium", [], 0x0) = 0',send(10)])

    def test_split_never_excuses_external_or_unknown_socket_destinations(self):
        prefix=['10<chromium> 1.000000 socket(AF_INET, SOCK_STREAM, IPPROTO_TCP) = 60',
            '10<chromium> 1.000001 connect(60, {sa_family=AF_INET, sin_port=htons(443), sin_addr=inet_addr("198.51.100.99")}, 16) = -1 ENETUNREACH',
            '10<chromium> 1.000002 clone(child_stack=NULL, flags=CLONE_FILES|SIGCHLD) = 11',
            '11<chromium> 1.000003 unshare(CLONE_FILES) = 0',
            '11<chromium> 1.000004 close(60) = 0']
        attempts,_=observer.parse(prefix+[send(10)])
        self.assertEqual([a.address for a in attempts],['198.51.100.99','198.51.100.99'])
        with self.assertRaises(observer.NetworkObservationError):observer.parse(prefix+[send(11)])


if __name__=='__main__':unittest.main()
