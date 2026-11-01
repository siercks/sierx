"""Corroborate terminal ptrace entries with a complete, loss-free kernel trace."""
from collections import defaultdict
import hashlib
import math
import re

CALLS = {'connect', 'sendto', 'sendmsg', 'sendmmsg'}
LOSS_KEYS = {'overrun', 'commit overrun', 'dropped events'}
EVENTS = sorted(['syscalls/sys_'+direction+'_'+call for call in CALLS for direction in ('enter','exit')]
                + ['sched/sched_process_exit'])


def integer(value, minimum=0, maximum=2**63-1):
    return type(value) is int and minimum <= value <= maximum


class KernelEvidence:
    def __init__(self, metadata, text, cpus, suite):
        if (not isinstance(metadata, dict) or type(metadata.get('schema')) is not int or metadata.get('schema') != 1
                or metadata.get('observer') != 'kernel-syscalls-v1' or metadata.get('clock') != 'mono'
                or metadata.get('calls') != sorted(CALLS) or metadata.get('complete') is not True
                or type(cpus) is not int or cpus not in {2, 4}
                or not isinstance(suite, str) or not re.fullmatch('[a-f0-9]{64}', suite)
                or metadata.get('suite_sha256') != suite):
            raise ValueError('Kernel syscall coverage is missing or incomplete')
        if metadata.get('trace_sha256') != hashlib.sha256(text.encode()).hexdigest():
            raise ValueError('Kernel trace checksum does not match its capture')
        losses = metadata.get('losses')
        if (not isinstance(losses, dict) or set(losses) != {'cpu'+str(i) for i in range(cpus)}
                or any(not isinstance(row, dict) or set(row) != LOSS_KEYS
                       or any(type(value) is not int or value != 0 for value in row.values())
                       for row in losses.values())):
            raise ValueError('Kernel syscall trace lost events or has unreadable loss counters')
        samples = []
        for name in ('start', 'end'):
            control = metadata.get(name)
            if (not isinstance(control, dict) or not integer(control.get('pid'), 1, 0x7fffffff)
                    or not integer(control.get('fd'), 0, 0x7fffffff)):
                raise ValueError('Kernel observer control identity is missing')
            config=control.get('configuration')
            mask=config.get('cpu_mask') if isinstance(config,dict) else None
            if (not isinstance(config,dict) or config.get('clock')!='mono'
                    or config.get('pid_filter')!='' or config.get('excluded_pids')!=''
                    or not isinstance(mask,str) or not re.fullmatch('[0-9a-fA-F,]+',mask)
                    or int(mask.replace(',',''),16) & ((1<<cpus)-1) != (1<<cpus)-1
                    or config.get('events')!={event:{'enabled':'1','filter':'none'} for event in EVENTS}):
                raise ValueError('Kernel event configuration or CPU/process coverage is incomplete')
            clock = control.get('sample')
            if (not isinstance(clock, list) or len(clock) != 3 or not all(integer(n) for n in clock)
                    or not 0 <= clock[2]-clock[0] <= 100_000_000):
                raise ValueError('Kernel observer clock sample is unreadable')
            samples.append(clock)
        self.begin, self.end = samples[0][0]/1e9, samples[1][2]/1e9
        if not 0 < self.end-self.begin <= 11000:
            raise ValueError('Kernel observer interval is invalid')
        lower = min(row[1]-row[2] for row in samples)
        upper = max(row[1]-row[0] for row in samples)
        if not 0 <= upper-lower <= 200_000_000:
            raise ValueError('Kernel and ptrace clocks cannot be correlated')
        self.offset_lower, self.offset_upper = lower/1e9, upper/1e9
        self.entries, self.exits, returns = defaultdict(list), defaultdict(list), defaultdict(list)
        self.return_events=defaultdict(list)
        prefix = re.compile(r'^\s*.+-(\d+)\s+\[(\d+)\]\s+\S+\s+(\d+\.\d+):\s+(.*)$')
        started=False
        for line in text.splitlines():
            if not line.strip(): continue
            match = prefix.match(line)
            if not match:
                # Header comments precede events. A task can name itself with
                # '#', so match real event structure before treating any header.
                if not started and line.startswith('#'): continue
                raise ValueError('Kernel trace record could not be decoded')
            started=True
            pid, cpu, timestamp, body = match.groups()
            timestamp = float(timestamp)
            if (not 0 < int(pid) <= 0x7fffffff or int(cpu) >= cpus or not math.isfinite(timestamp)
                    or not self.begin-10 <= timestamp <= self.end+10):
                raise ValueError('Kernel trace record is outside its captured interval')
            entered = re.match(r'sys_(connect|sendto|sendmsg|sendmmsg)\(', body)
            returned = re.fullmatch(r'sys_(connect|sendto|sendmsg|sendmmsg) -> ((?:0x)?[0-9a-f]+|-[0-9]+)', body)
            if entered:
                descriptor = re.search(r'\bfd:\s*((?:0x)?[0-9a-f]+)(?:,|\))', body)
                if not descriptor: raise ValueError('Kernel socket descriptor is unreadable')
                value = descriptor[1]
                # Syscall event arguments use the kernel's hexadecimal %lx
                # format, which need not include a 0x prefix.
                self.entries[int(pid)].append((timestamp, entered[1], int(value, 16)))
            elif returned:
                value = returned[2]
                value = int(value, 10 if value.startswith('-') else 16)
                if not -2**63 <= value < 2**64: raise ValueError('Kernel return value is out of range')
                if value >= 2**63: value -= 2**64
                returns[(int(pid), returned[1])].append((timestamp, value))
                self.return_events[int(pid)].append(timestamp)
            elif body.startswith('sched_process_exit:'):
                identity = re.search(r' pid=([0-9]+) prio=[0-9]+$', body)
                if not identity or identity[1] != pid:
                    raise ValueError('Kernel process-exit identity is ambiguous')
                self.exits[int(pid)].append(timestamp)
            else:
                raise ValueError('Unexpected event in the kernel syscall trace')
        for name in ('start', 'end'):
            control = metadata[name]
            entries = [row for row in self.entries[control['pid']]
                       if row[1:] == ('sendto', control['fd'])]
            exits = returns[(control['pid'], 'sendto')]
            if (len(entries) != 1 or len(exits) != 1 or exits[0][1] != 5
                    or not self.begin <= entries[0][0] <= exits[0][0] <= self.end):
                raise ValueError('A kernel observer positive control is missing')
        controls=metadata['start']
        for name in ('executed_control','cancelled_control'):
            control=controls.get(name)
            if (not isinstance(control,dict) or set(control)!={'pid','timestamp'} or not integer(control.get('pid'),1,0x7fffffff)
                    or type(control.get('timestamp')) not in {int,float}
                    or not math.isfinite(control['timestamp'])):
                raise ValueError('Kernel execution controls are missing')
        identities=[metadata['start']['pid'],metadata['end']['pid'],
                    controls['executed_control']['pid'],controls['cancelled_control']['pid']]
        executed=controls['executed_control']['pid']
        entered=self.entries.get(executed,[])
        exited=returns.get((executed,'sendto'),[])
        deaths=self.exits.get(executed,[])
        if (len(entered)!=1 or entered[0][1:]!=('sendto',999) or len(exited)!=1 or exited[0][1]!=-9
                or len(deaths)!=1 or not entered[0][0]<=exited[0][0]<=deaths[0]):
            raise ValueError('Executed kernel control was not observed from entry through exit')
        if (len(set(identities)) != 4
                or self.cancelled_before_entry(**controls['executed_control'])
                or self.entries.get(controls['cancelled_control']['pid'])
                or not self.cancelled_before_entry(**controls['cancelled_control'])):
            raise ValueError('Kernel execution controls did not distinguish a cancelled syscall')

    def cancelled_before_entry(self, pid, timestamp):
        """Only a terminal, never-executed entry may avoid destination decoding.

        Ptrace stops precede kernel syscall tracepoints. Any kernel entry in the
        conservative clock interval, missing death or PID reuse keeps rejection.
        """
        pid = int(pid)
        lower = timestamp-self.offset_upper-0.001
        upper = timestamp-self.offset_lower+0.001
        deaths = self.exits.get(pid, [])
        if (len(deaths) != 1 or lower < self.begin or upper > self.end
                or not upper <= deaths[0] <= min(self.end, lower+20)):
            return False
        # Requiring no network execution anywhere in this TID's captured
        # lifetime also covers delayed/misordered userspace trace rendering.
        return not self.entries.get(pid) and not self.return_events.get(pid)

    def covers_start(self, timestamp):
        return timestamp-self.offset_upper >= self.begin

    @staticmethod
    def summary():
        return {'result':'passed', 'observer':'kernel-syscalls-v1', 'lost_events':0,
                'positive_controls':2,'execution_controls':2}
