"""Corroborate terminal ptrace entries with a complete, loss-free kernel trace."""
from collections import defaultdict
import errno
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
        self.returned_calls=defaultdict(list)
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
                self.returned_calls[int(pid)].append((timestamp, returned[1], value))
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
        cancelled=controls['cancelled_control']
        cancelled_pid=cancelled['pid']
        window=self._terminal_window(**cancelled)
        observed_returns=self.return_events.get(cancelled_pid, [])
        sendto_returns=returns.get((cancelled_pid,'sendto'), [])
        # The guest explicitly kills this known ptrace-stopped child and
        # verifies SIGKILL. On x86, the syscall exit path can log ENOSYS even
        # though the sendto entry tracepoint was never reached. Accept that
        # exact evidence only for this deliberate control, never app traffic.
        aborted_return=(window is not None and len(observed_returns)==1 and len(sendto_returns)==1
                        and sendto_returns[0][1]==-errno.ENOSYS
                        and window[0]<=sendto_returns[0][0]<=window[1])
        if (len(set(identities)) != 4 or self.entries.get(cancelled_pid)
                or window is None or (observed_returns and not aborted_return)):
            raise ValueError('Kernel execution controls did not distinguish a cancelled syscall')

    def _terminal_window(self, pid, timestamp):
        lower = timestamp-self.offset_upper-0.001
        upper = timestamp-self.offset_lower+0.001
        deaths = self.exits.get(pid, [])
        if (len(deaths) != 1 or lower < self.begin or upper > self.end
                or not upper <= deaths[0] <= min(self.end, lower+20)):
            return None
        return upper, deaths[0]

    def cancelled_before_entry(self, pid, timestamp):
        """Only a terminal, never-executed entry may avoid destination decoding."""
        pid = int(pid)
        if self._terminal_window(pid,timestamp) is None:
            return False
        # Requiring no network execution anywhere in this TID's captured
        # lifetime also covers delayed/misordered userspace trace rendering.
        return not self.entries.get(pid) and not self.return_events.get(pid)

    def terminal_without_execution(self, pid, timestamp, history):
        """Require a bijection for ALL completed calls, not just empty late windows.

        A thread may have performed earlier, fully decoded sends before dying
        at a new ptrace entry stop. Every prior call must have exactly one
        matching kernel entry AND return (name, descriptor, result and order),
        before the terminal uncertainty interval. No orphan, restarted, extra,
        missing or overlapping execution can be assigned to the terminal stop.
        The caller still classifies all completed/explicit outgoing attempts.
        """
        return self._terminal_ledger(pid,timestamp,history)[0]

    def _terminal_ledger(self,pid,timestamp,history):
        pid=int(pid)
        if self._terminal_window(pid,timestamp) is None or not history:
            return False,0,'not-terminal'
        if history[-1][0]!=timestamp or history[-1][3] is not None:
            return False,0,'ptrace-incomplete'
        prior=history[:-1]
        entries=self.entries.get(pid,[])
        returns=self.returned_calls.get(pid,[])
        if len(entries)!=len(prior) or len(returns)!=len(prior):
            return False,0,'count-mismatch'
        terminal_lower=timestamp-self.offset_upper-0.001
        previous_exit=self.begin
        for index,((when,call,descriptor,result),entry,returned) in enumerate(zip(prior,entries,returns)):
            next_time=history[index+1][0]
            lower=when-self.offset_upper-0.001
            upper=next_time-self.offset_lower+0.001
            if (result is None or descriptor is None
                    or entry[1:]!=(call,descriptor) or returned[1:]!=(call,result)):
                return False,index,'call-mismatch'
            if (when>=next_time or not self.begin<=lower<=entry[0]<=returned[0]<terminal_lower
                    or previous_exit>entry[0] or returned[0]>upper):
                return False,index,'time-mismatch'
            previous_exit=returned[0]
        return True,len(prior),'verified'

    def cancellation_diagnostic(self,pid,timestamp,history=None):
        """Payload-free explanation only; never changes the exclusion decision."""
        pid=int(pid)
        lower=timestamp-self.offset_upper-0.001
        upper=timestamp-self.offset_lower+0.001
        entries=self.entries.get(pid,[])
        returns=self.return_events.get(pid,[])
        diagnostic={'terminal_window':self._terminal_window(pid,timestamp) is not None,
                'ptrace_time_in_capture':self.begin<=lower<=upper<=self.end,
                'network_entries':len(entries),'network_returns':len(returns),
                'process_exits':len(self.exits.get(pid,[])),
                'entries_in_or_after_window':sum(row[0]>=lower for row in entries),
                'returns_in_or_after_window':sum(when>=lower for when in returns)}
        if history is not None:
            _,matched,status=self._terminal_ledger(pid,timestamp,history)
            diagnostic.update(trace_network_records=len(history),matched_prior_calls=matched,ledger_status=status)
        return diagnostic

    def covers_start(self, timestamp):
        return timestamp-self.offset_upper >= self.begin

    @staticmethod
    def summary():
        return {'result':'passed', 'observer':'kernel-syscalls-v1', 'lost_events':0,
                'positive_controls':2,'execution_controls':2}
