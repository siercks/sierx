"""A terminal ptrace stop needs independent, loss-free non-execution proof."""
import copy
import hashlib
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]/'scripts'))
import kernel_network_evidence as kernel
import network_observer as observer


def fixture():
    metadata={'schema':1,'observer':'kernel-syscalls-v1','suite_sha256':'a'*64,
        'clock':'mono','calls':sorted(kernel.CALLS),'complete':True,
        'start':{'pid':1,'fd':3,'sample':[100*10**9,1100*10**9,100*10**9],
                 'executed_control':{'pid':3,'timestamp':1100.1},
                 'cancelled_control':{'pid':4,'timestamp':1100.2}},
        'end':{'pid':2,'fd':4,'sample':[110*10**9,1110*10**9,110*10**9]},
        'losses':{name:{key:0 for key in kernel.LOSS_KEYS} for name in ('cpu0','cpu1')}}
    for key in ('start','end'):
        metadata[key]['configuration']={'clock':'mono','cpu_mask':'3','pid_filter':'','excluded_pids':'',
            'events':{event:{'enabled':'1','filter':'none'} for event in kernel.EVENTS}}
    lines=['root-1 [000] .... 100.010000: sys_sendto(fd: 0x3, buff: 0x1234, len: 5)',
        'root-1 [000] .... 100.011000: sys_sendto -> 0x5',
        'root-3 [000] .... 100.101000: sys_sendto(fd: 3e7, buff: 0x1234, len: 5)',
        'root-3 [000] .... 100.102000: sys_sendto -> 0xfffffffffffffff7',
        'root-3 [000] .... 100.103000: sched_process_exit: comm=root pid=3 prio=120',
        'root-4 [000] .... 100.210000: sched_process_exit: comm=root pid=4 prio=120',
        'task-10 [000] .... 102.000000: sched_process_exit: comm=task pid=10 prio=120',
        'root-2 [001] .... 109.010000: sys_sendto(fd: 0x4, buff: 0x5678, len: 5)',
        'root-2 [001] .... 109.011000: sys_sendto -> 0x5']
    return metadata, lines


def proof(metadata=None, lines=None):
    default_metadata, default_lines=fixture()
    metadata=copy.deepcopy(metadata if metadata is not None else default_metadata)
    text='\n'.join(lines if lines is not None else default_lines)
    metadata.setdefault('trace_sha256',hashlib.sha256(text.encode()).hexdigest())
    return kernel.KernelEvidence(metadata,text,2,'a'*64)


class KernelEvidenceTests(unittest.TestCase):
    def test_kernel_hexadecimal_fields_without_prefix_are_not_decimal(self):
        metadata,lines=fixture()
        metadata['start']['fd']=61
        lines[0]=lines[0].replace('fd: 0x3,','fd: 3d,')
        self.assertTrue(proof(metadata,lines).cancelled_before_entry(10,1101.0))

    def test_only_unreturned_terminal_unexecuted_entries_can_be_corroborated(self):
        line='10<python3> 1101.000000 sendto(5, "private payload", 15, 0, NULL, 0) <unfinished ...>'
        with self.assertRaises(observer.NetworkObservationError): observer.parse([line])
        stats={}
        self.assertEqual(observer.parse([line],stats,proof())[0],[])
        self.assertEqual(stats['cancelled_before_kernel_entry']['installer'],1)
        metadata,lines=fixture()
        for extra in (
            '#renamed-10 [000] .... 101.001000: sys_sendto(fd: 0x5, buff: 0x9999, len: 5)',
            'task-10 [000] .... 100.900000: sys_sendto(fd: 0x5, buff: 0x9999, len: 5)',
            'task-10 [000] .... 101.001000: sys_sendto(fd: 0x5, buff: 0x9999, len: 5)',
            'task-10 [000] .... 101.001000: sys_connect(fd: 0x99, uservaddr: 0x9999, addrlen: 16)',
            'task-10 [000] .... 101.001000: sys_sendto -> 0xffffffffffffffff',
            'task-10 [000] .... 103.000000: sched_process_exit: comm=reused pid=10 prio=120',
        ):
            with self.subTest(extra=extra),self.assertRaises(observer.NetworkObservationError):
                observer.parse([line],kernel=proof(metadata,lines+[extra]))
        for changed in (line.replace(' <unfinished ...>',' = -1 EBADF'),
                        line.replace(' <unfinished ...>',' = ? ERESTARTSYS')):
            with self.subTest(returned=changed),self.assertRaises(observer.NetworkObservationError):
                observer.parse([changed],kernel=proof())
        with self.assertRaises(observer.NetworkObservationError):
            observer.parse([line],kernel=proof(metadata,[l for l in lines if 'task-10' not in l]))
        with self.assertRaises(ValueError):observer.parse([line.replace('1101.000000','1099.000000')],kernel=proof())

    def test_explicit_external_attempts_are_never_excused_even_before_kernel_entry(self):
        line='10<python3> 1101.000000 sendto(5, "probe", 5, 0, {sa_family=AF_INET, sin_port=htons(443), sin_addr=inet_addr("198.51.100.99")}, 16) <unfinished ...>'
        attempts,_=observer.parse([line],kernel=proof())
        self.assertEqual([(a.address,a.port) for a in attempts],[('198.51.100.99',443)])

    def test_loss_missing_controls_wrong_suite_clock_jumps_and_bad_records_fail_closed(self):
        metadata,lines=fixture()
        broken=[]
        for key,value in (('complete',False),('schema',True),('suite_sha256','b'*64),('calls',['sendto'])):
            row=copy.deepcopy(metadata);row[key]=value;broken.append(row)
        for key in kernel.LOSS_KEYS:
            row=copy.deepcopy(metadata);row['losses']['cpu0'][key]=1;broken.append(row)
        row=copy.deepcopy(metadata);row['losses'].pop('cpu1');broken.append(row)
        row=copy.deepcopy(metadata);row['end']['sample'][1]+=10**9;broken.append(row)
        row=copy.deepcopy(metadata);row['start']['executed_control']['pid']=9;broken.append(row)
        row=copy.deepcopy(metadata);row['trace_sha256']='0'*64;broken.append(row)
        row=copy.deepcopy(metadata);row['start']['configuration']['cpu_mask']='1';broken.append(row)
        row=copy.deepcopy(metadata);row['end']['configuration']['excluded_pids']='10';broken.append(row)
        row=copy.deepcopy(metadata);row['end']['configuration']['events'][kernel.EVENTS[0]]['enabled']='0';broken.append(row)
        for row in broken:
            with self.subTest(metadata=row),self.assertRaises(ValueError):proof(row,lines)
        for changed in (lines[1:], [l.replace('-> 0x5','-> 0x4') for l in lines],
                        lines+['private malformed kernel record'],lines+['# private injected record']):
            with self.subTest(lines=changed),self.assertRaises(ValueError):proof(metadata,changed)


if __name__=='__main__':unittest.main()
