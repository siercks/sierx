"""Root-only syscall corroboration inside the owned disposable acceptance VM."""
import json
import ctypes
import hashlib
import os
from pathlib import Path
import re
import socket
import subprocess
import signal
import struct
import sys
import time

from kernel_network_evidence import CALLS, EVENTS, LOSS_KEYS

DIRECTORY = Path('/var/log/sierx-network')
TRACE = Path('/sys/kernel/tracing/instances/sierx-offline')


def sample():
    before = time.monotonic_ns()
    real = time.time_ns()
    return [before, real, time.monotonic_ns()]


def control():
    sender, receiver = socket.socketpair()
    with sender, receiver:
        # Linux implements this send through sendto; the host requires its
        # independently observed kernel entry and successful exit.
        assert sender.send(b'probe') == 5
        assert receiver.recv(5) == b'probe'
        return {'pid':os.getpid(), 'fd':sender.fileno()}


def configuration():
    def pids(name):
        value=(TRACE/name).read_text().strip()
        return '' if value in {'','no pid'} else value
    return {'clock':re.search(r'\[([a-z_]+)\]',(TRACE/'trace_clock').read_text())[1],
            'cpu_mask':(TRACE/'tracing_cpumask').read_text().strip(),
            'pid_filter':pids('set_event_pid'),'excluded_pids':pids('set_event_notrace_pid'),
            'events':{event:{'enabled':(TRACE/'events'/event/'enable').read_text().strip(),
                             'filter':(TRACE/'events'/event/'filter').read_text().strip()} for event in EVENTS}}


def execution_control(cancel):
    """Verify this guest's ptrace/kernel ordering, with an invalid FD only."""
    libc=ctypes.CDLL(None,use_errno=True)
    libc.ptrace.argtypes=[ctypes.c_uint,ctypes.c_int,ctypes.c_void_p,ctypes.c_void_p]
    libc.ptrace.restype=ctypes.c_long
    libc.sendto.argtypes=[ctypes.c_int,ctypes.c_void_p,ctypes.c_size_t,ctypes.c_int,ctypes.c_void_p,ctypes.c_uint]
    def ptrace(request,pid,address=None,data=None):
        value=libc.ptrace(request,pid,address,data)
        if value == -1: raise OSError(ctypes.get_errno(),'Kernel observation control failed')
    expected={'x86_64':44,'aarch64':206}[os.uname().machine]
    pid=os.fork()
    if pid == 0:
        try:
            payload=ctypes.create_string_buffer(b'probe')
            ptrace(0,0)
            os.kill(os.getpid(),signal.SIGSTOP)
            libc.sendto(999,ctypes.cast(payload,ctypes.c_void_p),5,0,None,0)
            os._exit(0)
        except BaseException: os._exit(91)
    _,status=os.waitpid(pid,0)
    assert os.WIFSTOPPED(status)
    ptrace(0x4200,pid,None,ctypes.c_void_p(1))
    for _ in range(1000):
        ptrace(24,pid)
        _,status=os.waitpid(pid,0)
        assert os.WIFSTOPPED(status)
        info=ctypes.create_string_buffer(128)
        ptrace(0x420e,pid,ctypes.c_void_p(128),ctypes.cast(info,ctypes.c_void_p))
        if info.raw[0] == 1 and struct.unpack_from('=Q',info.raw,24)[0] == expected: break
    else: raise ValueError('Kernel execution control did not reach its syscall')
    timestamp=time.time()
    if cancel:
        time.sleep(0.01)
        os.kill(pid,signal.SIGKILL)
        _,status=os.waitpid(pid,0)
        assert os.WIFSIGNALED(status) and os.WTERMSIG(status)==signal.SIGKILL
    else:
        ptrace(24,pid)
        _,status=os.waitpid(pid,0)
        info=ctypes.create_string_buffer(128)
        ptrace(0x420e,pid,ctypes.c_void_p(128),ctypes.cast(info,ctypes.c_void_p))
        assert info.raw[0] == 2 and struct.unpack_from('=q',info.raw,24)[0] == -9
        ptrace(7,pid)
        _,status=os.waitpid(pid,0)
        assert os.WIFEXITED(status) and os.WEXITSTATUS(status)==0
    return {'pid':pid,'timestamp':timestamp}


def start():
    mount = TRACE.parent.parent
    if not (mount/'trace_clock').exists():
        subprocess.run(['mount','-t','tracefs','nodev',str(mount)],check=True,
                       stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
    TRACE.mkdir()
    (TRACE/'tracing_on').write_text('0')
    (TRACE/'current_tracer').write_text('nop')
    (TRACE/'trace_clock').write_text('mono')
    (TRACE/'buffer_size_kb').write_text('65536')
    (TRACE/'trace').write_text('')
    for name in EVENTS: (TRACE/'events'/name/'enable').write_text('1')
    (TRACE/'tracing_on').write_text('1')
    clock = sample()
    entry = control()
    entry['sample'] = clock
    entry['executed_control']=execution_control(False)
    entry['cancelled_control']=execution_control(True)
    entry['configuration']=configuration()
    (DIRECTORY/'kernel-start.json').write_text(json.dumps(entry)+'\n')


def finish():
    # Both the path unit and an early service-exit hook can request completion.
    # The output is written atomically; a second completion cannot replace it.
    import fcntl
    with (DIRECTORY/'kernel-finish.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        metadata = DIRECTORY/'kernel.json'
        if metadata.exists(): return
        end = control()
        end['sample'] = sample()
        (TRACE/'tracing_on').write_text('0')
        end['configuration']=configuration()
        losses = {}
        for file in sorted((TRACE/'per_cpu').glob('cpu*/stats')):
            row = {}
            for line in file.read_text().splitlines():
                key, _, value = line.partition(':')
                if key.strip() in LOSS_KEYS: row[key.strip()] = int(value.strip())
            losses[file.parent.name] = row
        text=(TRACE/'trace').read_text()
        (DIRECTORY/'kernel.trace').write_text(text)
        value = {'schema':1, 'observer':'kernel-syscalls-v1', 'clock':'mono', 'calls':sorted(CALLS),
                 'complete':True, 'start':json.loads((DIRECTORY/'kernel-start.json').read_text()),
                 'end':end, 'losses':losses,
                 'trace_sha256':hashlib.sha256(text.encode()).hexdigest(),
                 'suite_sha256':(DIRECTORY/'suite.sha256').read_text().strip()}
        pending = metadata.with_suffix('.pending')
        pending.write_text(json.dumps(value)+'\n')
        pending.replace(metadata)
        os.sync()
        result = json.loads(Path('/home/acceptance/result.json').read_text())
        suite = (DIRECTORY/'suite.sha256').read_text().strip()
        if result.get('result') not in {'passed','failed'} or not re.fullmatch('[a-f0-9]{64}',suite):
            raise ValueError('Guest completion identity is invalid')
        print('SIERX_FINISHED: '+suite+' '+result['result'],flush=True)


if __name__ == '__main__':
    if os.geteuid() != 0 or sys.argv[1:] not in (['start'], ['finish']):
        raise SystemExit('Kernel observation requires its root-owned guest unit')
    os.umask(0o077)
    if sys.argv[1] == 'start': start()
    else: finish()
