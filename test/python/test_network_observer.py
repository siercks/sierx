"""An observer must detect blocked attempts and cannot be fooled by payload text."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
import network_observer as observer


def address(ip,port):
    if ':' in ip:return '{sa_family=AF_INET6, sin6_port=htons(%d), inet_pton(AF_INET6, "%s", &sin6_addr), sin6_scope_id=0}'%(port,ip)
    return '{sa_family=AF_INET, sin_port=htons(%d), sin_addr=inet_addr("%s")}'%(port,ip)


def evidence():
    programs={'installer':'python3','app':'sierx','gateway':'caddy','database':'postgres','chromium':'headless_shell','firefox':'firefox','network-proxy':'slirp4netns'}
    lines=[f'{index+1}<runner> 1.000000 execve("/usr/bin/{program}", ["fixture"], 0x0 /* vars */) = 0' for index,program in enumerate(programs.values())]
    controls=[]
    for index,(name,(role,ip,port,protocol)) in enumerate(observer.CONTROLS.items()):
        start=10+index
        controls.append({'name':name,'start':start,'end':start+0.5})
        program=programs[role]
        prefix=f'{100+index}<{program}> {start+0.1:.6f} '
        family='AF_INET6' if ':' in ip else 'AF_INET'
        lines.append(prefix+f'socket({family}, SOCK_DGRAM, IPPROTO_UDP) = 3' if protocol=='udp' else prefix+f'socket({family}, SOCK_STREAM, IPPROTO_TCP) = 3')
        call=f'sendto(3, "query", 5, 0, {address(ip,port)}, 16)' if protocol=='udp' else f'connect(3, {address(ip,port)}, 16)'
        lines.append(prefix+call+' = -1 ENETUNREACH (Network is unreachable)')
    return lines,controls


class NetworkObserverTests(unittest.TestCase):
    def test_unclassified_trace_diagnostic_reports_fixed_categories_without_leaking_prefix(self):
        private = 'private-password-or-process-label'
        for raw,prefix in (('[pid 10] 1.000001 connect(3, "'+private+'", 16) = -1 EFAULT','bracketed'),
                           ('10<'+private+'> no-timestamp recvmsg(9, <unfinished ...>','numbered'),
                           (private+' <... recvmsg resumed>{msg_name=NULL}, 0) = 1','other')):
            with self.subTest(prefix=prefix), self.assertRaises(ValueError) as caught:
                observer.parse([raw])
            detail=str(caught.exception)
            self.assertIn('prefix='+prefix,detail)
            self.assertNotIn(private,detail)
            self.assertLess(len(detail),220)
        operation='private_secret_operation'
        with self.assertRaises(ValueError) as caught:
            observer.parse(['invalid io_uring_'+operation+'(1) = 0'])
        self.assertIn('call=io_uring',str(caught.exception))
        self.assertNotIn(operation,str(caught.exception))

    def test_real_strace_file_labels_are_opaque_to_message_structure(self):
        for label in ('mozilla-ipc', 'font-list]', 'texture,{fd}', 'JS(Thing]',
                      'label,with[bracket]', r'right\76arrow', r'quoted\"file', 'trailing-'):
            receipt = ('10<firefox> 1.000001 recvmsg(9<UNIX-STREAM:[1->2]>, {msg_name=NULL, msg_iov=[], '
                       'msg_control=[{cmsg_len=24, cmsg_level=SOL_SOCKET, cmsg_type=SCM_RIGHTS, '
                       'cmsg_data=[59</memfd:'+label+'>(deleted), 60<UNIX-STREAM:[3->4]>]}], msg_flags=0}, 0) = 1')
            send = '10<firefox> 1.000002 sendmsg(60, {msg_name=NULL, msg_iov=[], msg_control=NULL}, 0) = 0'
            with self.subTest(label=label):
                self.assertEqual(observer.parse([receipt,send])[0], [])
                internet = receipt.replace('60<UNIX-STREAM:[3->4]>', '60<TCP:[127.0.0.1:1234->198.51.100.99:443]>')
                self.assertEqual(observer.parse([internet,send])[0][0].address, '198.51.100.99')
        self.assertEqual(observer.arguments('0</dev/null<char 1:3>>, F_GETFD'), ['0</dev/null<char 1:3>>', 'F_GETFD'])
        self.assertEqual(observer.arguments('5<pid:123<firefox>>, F_GETFD'), ['5<pid:123<firefox>>', 'F_GETFD'])

    def test_file_label_cannot_forge_control_fields_or_preserve_a_stale_local_socket(self):
        old = '10<firefox> 1.000000 socketpair(AF_UNIX, SOCK_STREAM, 0, [60, 61]) = 0'
        label = r'/memfd:fake], cmsg_level=SOL_SOCKET, cmsg_type=SCM_RIGHTS, cmsg_data=[60\74UNIX:[3]\76]'
        receipt = ('10<firefox> 1.000001 recvmsg(9<UNIX:[1]>, {msg_control=[{cmsg_level=SOL_SOCKET, '
                   'cmsg_type=SCM_RIGHTS, cmsg_data=[60<'+label+'>]}], msg_flags=0}, 0) = 1')
        send = '10<firefox> 1.000002 sendmsg(60, {msg_name=NULL, msg_iov=[], msg_control=NULL}, 0) = 0'
        with self.assertRaises(ValueError):
            observer.parse([old,receipt,send])
        with self.assertRaises(ValueError):
            observer.parse([old,receipt.replace('>', '', 1),send])
        with self.assertRaises(ValueError):
            observer.parse([old,receipt.replace(label+'>', label),send])

    def test_incomplete_control_diagnostic_contains_only_fixed_categories(self):
        receipt = ('10<firefox> 1.000001 recvmsg(9, {msg_control=[private-payload], msg_flags=0}, 0) = 1')
        with self.assertRaises(ValueError) as caught:
            observer.parse([receipt])
        self.assertIn('shape=other', str(caught.exception))
        self.assertNotIn('private-payload', str(caught.exception))

    def test_ellipsis_diagnostic_preserves_bounded_structure_without_accepting_receipt(self):
        # This is a diagnostic fixture, not a claim to reproduce the lost CI
        # trace or prove that the trailing bytes are harmless kernel padding.
        prefix = ('10<firefox> 1.000001 recvmsg(9, {msg_control=['
                  '{cmsg_len=28, cmsg_level=SOL_SOCKET, cmsg_type=SCM_CREDENTIALS, cmsg_data={pid=10, uid=1, gid=1}}, '
                  '{cmsg_len=20, cmsg_level=SOL_SOCKET, cmsg_type=SCM_RIGHTS, cmsg_data=[60<UNIX:[2]>]}, ')
        for tail, category in (('...', 'bare'), ('... /* 0x7ff123abc */', 'address-comment')):
            receipt = prefix + tail + '], msg_controllen=60, msg_flags=MSG_CTRUNC}, 0) = 1'
            with self.subTest(tail=category), self.assertRaises(ValueError) as caught:
                observer.parse([receipt])
            detail = str(caught.exception)
            for expected in ('shape=ellipsis index=2', 'control-bytes=60', 'leading-lengths=28,20',
                             'leading-lengths-capped=0', 'tail='+category, 'terminal=1', 'kernel-ctrunc=1'):
                self.assertIn(expected, detail)
            self.assertNotIn('0x7ff123abc', detail)
            self.assertLess(len(detail), 400)

    def test_control_diagnostic_cannot_leak_payload_labels_or_unbounded_numeric_fields(self):
        private = 'private-password-or-payload'
        records = ', '.join('{cmsg_len='+('9'*1000 if i==0 else '20')+
                            ', cmsg_level=SOL_SOCKET, cmsg_type=SCM_RIGHTS, '
                            'cmsg_data=[60</memfd:'+private+'>]}' for i in range(8))
        receipt = ('10<firefox> 1.000001 recvmsg(9, {msg_control=['+records+', ... /* '+private+
                   ' */], msg_controllen='+private+', msg_flags=0}, 0) = 1')
        with self.assertRaises(ValueError) as caught:
            observer.parse([receipt])
        detail = str(caught.exception)
        self.assertIn('control-bytes=unknown', detail)
        self.assertIn('leading-lengths=unknown,20,20,20', detail)
        self.assertIn('leading-lengths-capped=1', detail)
        self.assertIn('tail=other terminal=1 kernel-ctrunc=0', detail)
        self.assertNotIn(private, detail)
        self.assertNotIn('9'*11, detail)
        self.assertLess(len(detail), 400)

    def test_kernel_discard_flag_still_requires_complete_metadata_for_every_returned_fd(self):
        receipt='10<firefox> 1.000001 recvmsg(9<UNIX:[1]>, {msg_control=[{cmsg_level=SOL_SOCKET, cmsg_type=SCM_RIGHTS, cmsg_data=[60<UNIX:[2]>]}], msg_flags=MSG_CTRUNC}, 0) = 1'
        send='10<firefox> 1.000002 sendmsg(60, {msg_name=NULL, msg_iov=[], msg_control=NULL}, 0) = 0'
        stats={}
        self.assertEqual(observer.parse([receipt,send],stats)[0],[])
        self.assertEqual(stats['kernel_control_truncations'],1)
        internet=receipt.replace('60<UNIX:[2]>','60<TCP:[127.0.0.1:1234->198.51.100.99:443]>')
        self.assertEqual(observer.parse([internet,send])[0][0].address,'198.51.100.99')
        for invalid in (receipt.replace('60<UNIX:[2]>','60'),receipt.replace('60<UNIX:[2]>','60, ...')):
            with self.subTest(receipt=invalid),self.assertRaises(ValueError):observer.parse([invalid,send])
        old='10<firefox> 1.000000 socketpair(AF_UNIX, SOCK_STREAM, 0, [60, 61]) = 0'
        empty='10<firefox> 1.000001 recvmsg(9<UNIX:[1]>, {msg_control=NULL, msg_controllen=0, msg_flags=MSG_CTRUNC}, 0) = 1'
        self.assertEqual(observer.parse([old,empty,send])[0],[])
        with self.assertRaises(ValueError):observer.parse([old,receipt.replace('60<UNIX:[2]>','60'),send])
        with self.assertRaises(ValueError):observer.parse([old,'10<firefox> 1.000001 recvmsg(9, {msg_control=[...], msg_flags=MSG_CTRUNC}, 0) = 1',send])

    def test_blocking_descriptor_receipt_installs_after_an_intervening_old_fd_close(self):
        lines=['10<firefox> 1.000000 socketpair(AF_UNIX, SOCK_STREAM, 0, [60, 61]) = 0',
               '10<firefox> 1.000001 clone(child_stack=NULL, flags=CLONE_FILES|CLONE_THREAD) = 11',
               '11<firefox> 1.000002 recvmsg(9<UNIX:[1]>, <unfinished ...>',
               '10<firefox> 1.000003 close(60<UNIX:[2]>) = 0',
               '11<firefox> 1.000004 <... recvmsg resumed>{msg_name=NULL, msg_iov=[], msg_control=[{cmsg_level=SOL_SOCKET, cmsg_type=SCM_RIGHTS, cmsg_data=[60<UNIX:[3]>]}], msg_flags=0}, 0) = 1',
               '10<firefox> 1.000005 sendmsg(60, {msg_name=NULL, msg_iov=[], msg_control=NULL}, 0) = 0']
        self.assertEqual(observer.parse(lines)[0], [])
        lines[4]=lines[4].replace('60<UNIX:[3]>','60<TCP:[127.0.0.1:1234->198.51.100.99:443]>')
        self.assertEqual(observer.parse(lines)[0][0].address,'198.51.100.99')

    def test_received_unix_socket_metadata_survives_opaque_sends_and_shared_threads(self):
        lines=['10<firefox> 1.000000 recvmsg(9<UNIX-STREAM:[1->2]>, {msg_name=NULL, msg_iov=[{iov_base="x", iov_len=1}], msg_control=[{cmsg_len=24, cmsg_level=SOL_SOCKET, cmsg_type=SCM_RIGHTS, cmsg_data=[59</memfd:mozilla-ipc>(deleted), 60<UNIX-STREAM:[123->124]>]}], msg_flags=0}, MSG_CMSG_CLOEXEC) = 1',
               '10<firefox> 1.000001 clone(child_stack=NULL, flags=CLONE_FILES|CLONE_THREAD) = 11',
               '11<firefox> 1.000002 sendmsg(60, {msg_name=NULL, msg_iov=[{iov_base="x", iov_len=1}], msg_control=NULL}, 0) = 1']
        self.assertEqual(observer.parse(lines)[0], [])
        lines[0]=lines[0].replace('60<UNIX-STREAM:[123->124]>', '60<TCP:[127.0.0.1:1234->198.51.100.99:443]>')
        attempts,_=observer.parse(lines)
        self.assertEqual([(a.address,a.port,a.protocol) for a in attempts],[('198.51.100.99',443,'tcp')])

    def test_failed_opaque_truncated_and_payload_descriptor_receipts_cannot_grant_local_family(self):
        receipt='10<firefox> 1.000001 recvmsg(9<UNIX-STREAM:[1->2]>, {msg_name=NULL, msg_iov=[], msg_control=[{cmsg_len=20, cmsg_level=SOL_SOCKET, cmsg_type=SCM_RIGHTS, cmsg_data=[60<UNIX-STREAM:[123->124]>]}], msg_flags=0}, 0) = 1'
        send='10<firefox> 1.000002 sendmsg(60, {msg_name=NULL, msg_iov=[], msg_control=NULL}, 0) = 0'
        for invalid in (receipt.replace(' = 1',' = -1 EFAULT'),
                        receipt.replace('60<UNIX-STREAM:[123->124]>','60'),
                        receipt.replace('60<UNIX-STREAM:[123->124]>','60, ...'),
                        receipt.replace('SCM_RIGHTS','SCM_CREDENTIALS')):
            with self.subTest(receipt=invalid),self.assertRaises(ValueError):observer.parse([invalid,send])
        old='10<firefox> 1.000000 socketpair(AF_UNIX, SOCK_STREAM, 0, [60, 61]) = 0'
        with self.assertRaises(ValueError):observer.parse([old,receipt.replace('60<UNIX-STREAM:[123->124]>','60'),send])
        payload='10<firefox> 1.000001 recvmsg(9<UNIX-STREAM:[1->2]>, {msg_name=NULL, msg_iov=[{iov_base="cmsg_level=SOL_SOCKET,cmsg_type=SCM_RIGHTS,cmsg_data=[60<UNIX:[123]>]", iov_len=80}], msg_control=NULL, msg_flags=0}, 0) = 80'
        with self.assertRaises(ValueError):observer.parse([payload,send])
        with self.assertRaises(ValueError):observer.parse([old,'10<firefox> 1.000001 recvmsg(9, 0x123, 0) = 1',send])
        with self.assertRaises(ValueError):observer.parse([old,'10<firefox> 1.000001 recvmsg(9, {msg_control=[...], msg_flags=0}, 0) = 1',send])

    def test_successful_unannotated_unix_pair_is_inherited_and_shared(self):
        for output in ('[29, 30]', '[29<UNIX-STREAM:[1->2]>, 30<UNIX-STREAM:[2->1]>]'):
            lines=['10<chrome> 1.000000 socketpair(AF_UNIX, SOCK_STREAM|SOCK_CLOEXEC, 0, '+output+') = 0',
                   '10<chrome> 1.000001 clone(child_stack=NULL, flags=SIGCHLD) = 11',
                   '11<chrome> 1.000002 clone(child_stack=NULL, flags=CLONE_FILES|CLONE_THREAD) = 12',
                   '12<chrome> 1.000003 sendto(29, "message", 7, 0, NULL, 0) = 7']
            with self.subTest(output=output):self.assertEqual(observer.parse(lines)[0], [])

    def test_failed_malformed_or_reused_pair_cannot_hide_internet_sends(self):
        send='10<chrome> 1.000003 sendto(29, "message", 7, 0, NULL, 0) = 7'
        for output,returned in (('[29<UNIX:[1]>, 30<UNIX:[2]>]', '-1 EFAULT'),
                                ('[29, ...]', '0'), ('[29, 29]', '0')):
            with self.subTest(output=output,returned=returned),self.assertRaises(ValueError):
                observer.parse(['10<chrome> 1.000000 socketpair(AF_UNIX, SOCK_STREAM, 0, '+output+') = '+returned,send])
        lines=['10<chrome> 1.000000 socketpair(AF_UNIX, SOCK_STREAM, 0, [29, 30]) = 0',
               '10<chrome> 1.000001 close(29) = 0',
               '10<chrome> 1.000002 socket(AF_INET, SOCK_STREAM, IPPROTO_TCP) = 29',send]
        with self.assertRaises(ValueError):observer.parse(lines)
        lines[3]='10<chrome> 1.000003 connect(29, '+address('198.51.100.99',443)+', 16) = -1 ENETUNREACH'
        self.assertEqual(observer.parse(lines)[0][0].address,'198.51.100.99')

    def test_long_control_window_requires_explicit_bounded_emulation_budget(self):
        lines, controls = evidence()
        controls[0]['end'] = controls[0]['start'] + 60
        with self.assertRaises(ValueError):
            observer.summarize(lines, controls)
        report = observer.summarize(lines, controls, control_interval_limit=120)
        self.assertEqual(report['control_interval_limit_seconds'], 120)
        for limit in (121, float('inf'), True):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                observer.summarize(lines, controls, control_interval_limit=limit)
        controls[0]['end'] = controls[0]['start'] + 121
        with self.assertRaises(ValueError):
            observer.summarize(lines, controls, control_interval_limit=120)

    def test_linux_all_zero_source_address_probes_are_local_but_dns_still_fails(self):
        lines,controls=evidence()
        for value in ('0.0.0.0','::'):
            family='AF_INET6' if ':' in value else 'AF_INET'
            probe=['999<postgres> 100.000000 socket('+family+', SOCK_DGRAM, IPPROTO_UDP) = 3',
                   '999<postgres> 100.000001 connect(3, '+address(value,5432)+', 16) = 0']
            with self.subTest(address=value):
                self.assertEqual(observer.summarize(lines+probe,controls)['external_attempts'],0)
                probe[1]=probe[1].replace('htons(5432)','htons(53)')
                with self.assertRaises(ValueError):observer.summarize(lines+probe,controls)

    def test_denied_ipv6_socket_setup_is_counted_separately_from_connections(self):
        stats={}
        attempts,_=observer.parse(['10<python3> 1.000000 socket(AF_INET6, SOCK_STREAM, IPPROTO_TCP) = -1 EAFNOSUPPORT'],stats)
        self.assertEqual(attempts,[])
        self.assertEqual(stats['blocked_ipv6_sockets'],1)

    def test_headless_shell_threads_and_slirp_proxy_have_canonical_roles(self):
        lines=['10<runner> 1.000000 execve("/opt/playwright/headless_shell", ["fixture"], 0x0) = 0',
               '10<headless_shell> 1.000001 clone(child_stack=NULL, flags=CLONE_FILES|CLONE_THREAD) = 11',
               '11<Chrome_ChildIOT> 1.000002 connect(3<TCP:[1]>, '+address('198.51.100.15',18181)+', 16) = -1 ENETUNREACH',
               '20<runner> 1.000003 execve("/usr/bin/slirp4netns", ["fixture"], 0x0) = 0',
               '20<slirp4netns> 1.000004 connect(3<TCP:[2]>, '+address('198.51.100.13',18181)+', 16) = -1 ENETUNREACH']
        attempts,executed=observer.parse(lines)
        self.assertEqual(executed,{'chromium','network-proxy'})
        self.assertEqual([entry.process for entry in attempts],['chromium','network-proxy'])

    def test_self_reexec_retains_known_executable_identity_without_trusting_argv(self):
        lines=['10<runner> 1.000000 execve("/usr/bin/podman", ["fixture"], 0x0) = 0',
               '10<podman> 1.000001 execve("/proc/self/exe", ["firefox"], 0x0) = 0',
               '10<podman> 1.000002 connect(3<TCP:[1]>, '+address('198.51.100.14',18182)+', 16) = -1 ENETUNREACH']
        attempts,executed=observer.parse(lines)
        self.assertEqual(executed,{'installer'})
        self.assertEqual(attempts[0].process,'installer')
        with self.assertRaises(ValueError):observer.parse(lines[1:])

    def test_container_child_pid_translation_preserves_the_browser_role(self):
        lines=['60<runner> 1.000000 execve("/opt/firefox", ["firefox"], 0x0) = 0',
               '60<firefox> 1.000001 clone(child_stack=NULL, flags=CLONE_FILES|CLONE_THREAD) = 2<firefox> /* 61 in strace\'s PID NS */',
               '61<Socket Thread> 1.000002 connect(3<TCP:[2]>, '+address('198.51.100.17',18181)+', 16) = -1 ENETUNREACH']
        attempts,_=observer.parse(lines)
        self.assertEqual(attempts[0].process,'firefox')

    def test_received_socket_identity_retains_the_exact_observed_peer(self):
        lines=['10<postgres> 1.000000 socket(AF_INET, SOCK_STREAM, IPPROTO_TCP) = 3<TCP:[1]>',
               '10<postgres> 1.000001 accept4(3<TCP:[1]>, '+address('198.51.100.99',1234)+', [128 => 16], 0) = 10<TCP:[123]>',
               '20<postgres> 1.000002 sendto(7<TCP:[123]>, "reply", 5, 0, NULL, 0) = 5']
        attempts,_=observer.parse(lines)
        self.assertEqual(attempts[0].address,'198.51.100.99')
        self.assertEqual(attempts[0].port,1234)

    def test_an_untraced_child_or_reused_socket_inode_cannot_hide_traffic(self):
        with self.assertRaises(ValueError):observer.parse(['20<node> 1.000000 clone(child_stack=NULL, flags=CLONE_UNTRACED|SIGCHLD) = 21'])
        lines=['10<node> 1.000000 socket(AF_INET, SOCK_STREAM, IPPROTO_TCP) = 3<TCP:[123]>',
               '10<node> 1.000001 connect(3<TCP:[123]>, '+address('127.0.0.1',443)+', 16) = 0',
               '10<node> 1.000002 close(3<TCP:[123]>) = 0',
               '10<node> 1.000003 socket(AF_INET, SOCK_STREAM, IPPROTO_TCP) = 3<TCP:[123]>',
               '10<node> 1.000004 sendto(3<TCP:[123]>, "payload", 7, 0, NULL, 0) = -1 ENOTCONN']
        with self.assertRaises(ValueError):observer.parse(lines)

    def test_browser_thread_names_keep_their_executed_process_identity(self):
        lines=['30<runner> 1.000000 execve("/opt/playwright/firefox/firefox", ["firefox"], 0x0) = 0',
               '30<firefox> 1.000001 clone(child_stack=NULL, flags=CLONE_VM|CLONE_FILES|CLONE_THREAD) = 31',
               '31<Socket Thread> 1.000002 connect(3<TCP:[2]>, '+address('198.51.100.17',18181)+', 16) = -1 ENETUNREACH']
        attempts,executed=observer.parse(lines)
        self.assertEqual(executed,{'firefox'})
        self.assertEqual(attempts[0].process,'firefox')

    def test_accepted_database_socket_is_inherited_before_a_child_reply(self):
        lines=['10<postgres> 1.000000 socket(AF_INET, SOCK_STREAM, IPPROTO_TCP) = 3<TCP:[1]>',
               '10<postgres> 1.000001 accept4(3<TCP:[1]>, <unfinished ...>',
               '10<postgres> 1.000002 <... accept4 resumed>'+address('198.51.100.99',1234)+', [128 => 16], SOCK_CLOEXEC) = 10<TCP:[2]>',
               '10<postgres> 1.000003 clone(child_stack=NULL, flags=SIGCHLD <unfinished ...>',
               '11<postgres> 1.000004 sendto(10<TCP:[2]>, "reply", 5, 0, NULL, 0) = 5',
               '10<postgres> 1.000005 <... clone resumed>) = 11',
               '10<postgres> 1.000006 close(10<TCP:[2]>) = 0',
               '11<postgres> 1.000007 sendto(10<TCP:[2]>, "reply", 5, 0, NULL, 0) = 5']
        attempts,_=observer.parse(lines)
        self.assertEqual([entry.address for entry in attempts],['198.51.100.99']*2)

    def test_thread_tables_and_duplicated_descriptors_keep_the_destination(self):
        lines=['20<python3> 1.000000 socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP) = 3',
               '20<python3> 1.000001 clone(child_stack=NULL, flags=CLONE_VM|CLONE_FILES|CLONE_THREAD) = 21',
               '21<python3> 1.000002 dup3(3, 8, O_CLOEXEC) = 8',
               '21<python3> 1.000003 connect(8, '+address('198.51.100.99',53)+', 16) = 0',
               '20<python3> 1.000004 sendmsg(8<UDP:[2]>, {msg_name=NULL, msg_namelen=0, msg_iov=[]}, 0) = 0']
        attempts,_=observer.parse(lines)
        self.assertEqual(len(attempts),2)
        self.assertTrue(all(entry.address=='198.51.100.99' and entry.protocol=='udp' for entry in attempts))

    def test_ipv4_mapped_ipv6_is_not_a_different_allowed_destination(self):
        attempts,_=observer.parse(['20<sierx> 1.000000 connect(3<TCPv6:[2]>, '+address('::ffff:198.51.100.99',443)+', 28) = -1 ENETUNREACH'])
        self.assertEqual(attempts[0].address,'198.51.100.99')

    def test_unobservable_async_io_and_unspecified_sends_fail_closed(self):
        for line in ('20<node> 1.000000 io_uring_setup(256, {flags=0}) = 3',
                     '20<node> 1.000000 io_uring_enter(3, 1, 1, 0, NULL, 0) = -1 EINTR',
                     '20<node> 1.000000 sendto(3, "payload", 7, 0, {sa_family=AF_UNSPEC}, 16) = 7'):
            with self.subTest(line=line),self.assertRaises(ValueError):observer.parse([line])

    def test_resumed_exec_retains_canonical_startup_coverage(self):
        lines=['42<runner> 1.000000 execve("/usr/local/bin/sierx", ["sierx"], 0x0 /* vars */ <unfinished ...>',
               '42<sierx> 1.000001 <... execve resumed>) = 0']
        _,executed=observer.parse(lines)
        self.assertEqual(executed,{'app'})
        with self.assertRaises(ValueError):observer.parse(lines[1:])

    def test_each_real_component_and_dns_udp_ipv6_control_must_be_seen(self):
        lines,controls=evidence()
        report=observer.summarize(lines,controls)
        self.assertEqual(report['external_attempts'],0)
        self.assertTrue(all(value==1 for value in report['negative_controls'].values()))
        for index,entry in enumerate(controls):
            with self.subTest(control=entry['name']),self.assertRaises(ValueError):
                observer.summarize(lines,[value for value in controls if value!=entry])

    def test_failed_and_unfinished_connects_are_still_external_attempts(self):
        lines,controls=evidence()
        for ending in (' = -1 ENETUNREACH (Network is unreachable)',' <unfinished ...>'):
            call='999<sierx> 100.000000 connect(9, '+address('198.51.100.99',443)+', 16)'+ending
            with self.subTest(ending=ending),self.assertRaises(ValueError) as caught:observer.summarize(lines+[call],controls)
            self.assertIn('app/tcp=1',str(caught.exception))
            self.assertNotIn('198.51.100.99',str(caught.exception))

    def test_failed_loopback_dns_lookup_is_not_treated_as_internal_traffic(self):
        lines,controls=evidence()
        call='999<node> 100.000000 connect(9<UDP:[1]>, '+address('127.0.0.1',53)+', 16) = -1 ECONNREFUSED'
        with self.assertRaises(ValueError):observer.summarize(lines+[call],controls)

    def test_broad_or_wrong_control_windows_do_not_excuse_egress(self):
        lines,controls=evidence()
        for change in ({'start':0,'end':1000},{'start':float('nan')},{'start':100,'end':101}):
            modified=[{**entry,**change} if entry['name']=='app-tcp' else entry for entry in controls]
            with self.subTest(change=change),self.assertRaises(ValueError):observer.summarize(lines,modified)

    def test_canonical_process_exec_and_complete_trace_are_required(self):
        lines,controls=evidence()
        with self.assertRaises(ValueError):observer.summarize(lines[1:],controls)
        for error in ('strace: Process 42 detached','strace: ptrace failed: Permission denied'):
            with self.subTest(error=error),self.assertRaises(ValueError):observer.summarize(lines,controls,trace_errors=error)

    def test_payload_that_looks_like_an_address_is_not_a_destination(self):
        line='42<node> 1.000000 sendto(3<UDP:[127.0.0.1:1->127.0.0.1:2]>, "sin_addr=inet_addr(\\\"198.51.100.99\\\")", 39, 0, '+address('127.0.0.1',2)+', 16) = 39'
        attempts,_=observer.parse([line])
        self.assertEqual([value.address for value in attempts],['127.0.0.1'])

    def test_connected_sends_and_batched_datagrams_retain_the_actual_destination(self):
        destination=address('198.51.100.99',53)
        lines=['42<python3> 1.000000 socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP) = 3',
               '42<python3> 1.000001 connect(3, '+destination+', 16) = 0',
               '42<python3> 1.000002 sendmsg(3, {msg_name=NULL, msg_namelen=0, msg_iov=[{iov_base="payload", iov_len=7}], msg_iovlen=1}, 0) = 7',
               '42<python3> 1.000003 sendmmsg(3, [{msg_hdr={msg_name='+destination+', msg_namelen=16, msg_iov=[], msg_iovlen=0}, msg_len=0}], 1, 0) = -1 ENETUNREACH (Network is unreachable)']
        attempts,_=observer.parse(lines)
        self.assertEqual(len(attempts),3)
        self.assertTrue(all(value.address=='198.51.100.99' and value.protocol=='udp' for value in attempts))

    def test_opaque_addresses_reused_fds_and_missing_entries_fail_closed(self):
        for call in ('42<sierx> 1.000000 connect(3, 0x123, 16) = -1 EFAULT (Bad address)',
                     '42<sierx> 1.000000 <... connect resumed>) = 0',
                     'unclassified connect(3, '+address('198.51.100.99',443)+', 16) = 0'):
            with self.subTest(call=call),self.assertRaises(ValueError):observer.parse([call])
        lines=['42<sierx> 1.000000 socket(AF_UNIX, SOCK_STREAM, 0) = 3',
               '42<sierx> 1.000001 close(3) = 0',
               '42<sierx> 1.000002 sendmsg(3, {msg_name=NULL, msg_iov=[]}, 0) = 0']
        with self.assertRaises(ValueError):observer.parse(lines)

    def test_internal_address_allowlist_cannot_hide_public_or_control_destinations(self):
        lines,controls=evidence()
        for value in ('198.51.100.11','8.8.8.8','2001:db8::16'):
            with self.subTest(value=value),self.assertRaises(ValueError):observer.summarize(lines,controls,[value])


if __name__=='__main__':unittest.main()
