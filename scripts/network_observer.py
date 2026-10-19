"""Parse private strace network records into payload-free attempted-egress proof.

Use one -f log with -Y -ttt -yy so forked processes and threads retain labels.
An unsuccessful connect/send is still an attempt. Unreadable destinations fail
closed rather than being reported as zero traffic.
"""
from dataclasses import dataclass
import ipaddress
import math
from pathlib import Path
import re

PROCESSES = {'installer', 'app', 'gateway', 'database', 'chromium', 'firefox','network-proxy'}
CONTROLS = {
    'app-tcp': ('app', '198.51.100.11', 18181, 'tcp'),
    'gateway-tcp': ('gateway', '198.51.100.12', 18181, 'tcp'),
    'database-tcp': ('database', '198.51.100.13', 18181, 'tcp'),
    'database-proxy-tcp': ('network-proxy', '198.51.100.13', 18181, 'tcp'),
    'installer-fetch': ('installer', '198.51.100.14', 18181, 'tcp'),
    'registry-pull': ('installer', '198.51.100.14', 18182, 'tcp'),
    'driver-node-fetch': ('installer', '198.51.100.14', 18183, 'tcp'),
    'dns-udp': ('installer', '198.51.100.16', 53, 'udp'),
    'ipv6-tcp': ('installer', '2001:db8::16', 18181, 'tcp'),
    'chromium-tcp': ('chromium', '198.51.100.15', 18181, 'tcp'),
    'firefox-tcp': ('firefox', '198.51.100.17', 18181, 'tcp'),
}


def component(name):
    name = Path(name).name
    if name == 'sierx': return 'app'
    if name == 'caddy': return 'gateway'
    if name in {'postgres', 'postmaster'}: return 'database'
    if name.startswith(('chrome', 'chromium')) or name=='headless_shell': return 'chromium'
    if name=='slirp4netns':return 'network-proxy'
    if name.startswith('firefox') or name in {'Socket Process', 'Web Content', 'RDD Process'}: return 'firefox'
    if name.startswith('python') or name in {'goose', 'sierxctl', 'podman', 'node', 'curl'}: return 'installer'
    return 'other'


def arguments(text):
    """Split strace arguments, without interpreting quoted payload contents."""
    result, start, depth, quoted, escaped = [], 0, 0, False, False
    for index, char in enumerate(text):
        if quoted:
            if escaped: escaped = False
            elif char == '\\': escaped = True
            elif char == '"': quoted = False
        elif char == '"': quoted = True
        elif char in '({[': depth += 1
        elif char in ')}]': depth -= 1
        elif char == ',' and depth == 0:
            result.append(text[start:index].strip()); start = index + 1
    result.append(text[start:].strip())
    return result


def field(text, name):
    for part in arguments(text.strip().removeprefix('{').removesuffix('}')):
        if part.startswith(name + '='):
            return part[len(name) + 1:]
    return None


def fd(text):
    match = re.match(r'([0-9]+)', text)
    return int(match[1]) if match else None


def socket_identity(text):
    match=re.search(r'<(?:TCPv6|TCP|UDPv6|UDP|UNIX(?:-[A-Z]+)?|NETLINK|socket):\[([0-9]+)(?=\]|,|->)',text)
    return match[1] if match else None


def endpoint(text):
    if not text or text == 'NULL': return None
    family = re.search(r'\bsa_family=(AF_[A-Z0-9]+)', text)
    if not family: raise ValueError('An outgoing socket address could not be decoded')
    family = family[1]
    if family in {'AF_UNIX', 'AF_NETLINK', 'AF_UNSPEC'}: return (family, '', 0)
    if family == 'AF_INET':
        address = re.search(r'\bsin_addr=inet_addr\("([^"]+)"\)', text)
        port = re.search(r'\bsin_port=htons\(([0-9]+)\)', text)
    elif family == 'AF_INET6':
        address = re.search(r'\binet_pton\(AF_INET6,\s*"([^"]+)"', text)
        port = re.search(r'\bsin6_port=htons\(([0-9]+)\)', text)
    else:
        raise ValueError('Unsupported outgoing socket family')
    if not address or not port: raise ValueError('Incomplete outgoing Internet address')
    parsed=ipaddress.ip_address(address[1])
    return (family, (getattr(parsed,'ipv4_mapped',None) or parsed).compressed, int(port[1]))


def inline_endpoint(text):
    if '<UNIX' in text: return ('AF_UNIX', '', 0)
    if '<NETLINK' in text: return ('AF_NETLINK', '', 0)
    match = re.search(r'->(?:\[([0-9a-fA-F:.]+)\]|([0-9.]+)):([0-9]+)', text)
    if match:
        address = ipaddress.ip_address(match[1] or match[2])
        return ('AF_INET6' if address.version == 6 else 'AF_INET', (getattr(address,'ipv4_mapped',None) or address).compressed, int(match[3]))
    return None


@dataclass(frozen=True)
class Attempt:
    timestamp: float
    process: str
    address: str
    port: int
    protocol: str


def records(lines):
    """Join unfinished/resumed syscalls, retaining the entry timestamp.

    Results for socket creation, accepts and forks are decoded at return. Replay
    them at entry order so inherited/shared descriptor tables exist before a
    child sends a reply. Incomplete outgoing entries still count as attempts.
    """
    pending, result = {}, []
    pattern = re.compile(r'^(\d+)(?:<([^>]+)>)?\s+([0-9]+\.[0-9]+)\s+(.*)$')
    for raw in lines:
        line = pattern.match(raw.strip())
        if not line:
            if re.search(r'\b(connect|sendto|sendmsg|sendmmsg)\(', raw):
                raise ValueError('An outgoing trace record could not be classified')
            continue
        pid, program, timestamp, body = line.groups()
        resumed = re.match(r'<\.\.\. ([a-z0-9_]+) resumed>(.*)', body)
        if resumed:
            entry=pending.pop((pid,resumed[1]),None)
            if entry is None:raise ValueError('Trace is missing a resumed syscall entry')
            result.append((*entry[:3],entry[3]+resumed[2]))
            continue
        call=re.match(r'([a-z0-9_]+)\(',body)
        if not call:continue
        entry=(pid,program or '',float(timestamp),body.split('<unfinished ...>',1)[0].rstrip())
        if '<unfinished ...>' in body:
            if (pid,call[1]) in pending:raise ValueError('Duplicate unfinished syscall entry')
            pending[(pid,call[1])]=entry
        else:result.append(entry)
    result.extend(pending.values())
    return sorted(result,key=lambda entry:entry[2])


def parse(lines,stats=None):
    stats={} if stats is None else stats
    stats.setdefault('blocked_io_uring_setups',0)
    stats.setdefault('blocked_ipv6_sockets',0)
    sockets, connected, attempts, executed, owners, roles, inode_family, inode_peer, members = {}, {}, [], set(), {}, {}, {}, {}, {}
    for pid,program,timestamp,body in records(lines):
        role=roles.get(pid,component(program))
        call = re.match(r'([a-z0-9_]+)\((.*)', body)
        if not call:continue
        name, tail = call.groups()
        returns=list(re.finditer(r'\)\s*=\s*(-?[0-9]+)',body))
        returned=int(returns[-1][1]) if returns else None
        text=body[call.start(2):returns[-1].start()] if returns else tail
        args = arguments(text)
        owner=owners.setdefault(pid,pid)
        owned=members.setdefault(owner,set())
        key=(owner,fd(args[0])) if args else (owner,None)
        identity=socket_identity(args[0]) if args else None
        if name.startswith('io_uring'):
            if name!='io_uring_setup' or returned is None or returned>=0:
                raise ValueError('Asynchronous I/O cannot be classified by this observer: pid='+pid+' role='+role+
                    ' call='+name+' result='+str(returned))
            stats['blocked_io_uring_setups']+=1
        if name in {'execve','execveat'} and returned==0:
            path=args[0] if name=='execve' else args[1]
            executable=re.match(r'"([^"]+)"',path)
            inherited=re.search(r'<([^>]+)>',args[0]) if name=='execveat' else None
            if executable and executable[1] in {'/proc/self/exe','/proc/thread-self/exe'}:
                if pid not in roles:raise ValueError('Self re-exec lacks a canonical startup identity')
            elif executable:roles[pid]=component(executable[1])
            elif inherited:roles[pid]=component(inherited[1])
            if executable or inherited:executed.add(roles[pid])
        if name in {'clone','clone3','fork','vfork'} and returned is not None and returned>0:
            if 'CLONE_UNTRACED' in text:raise ValueError('A child process escaped startup observation')
            translated=re.search(r"/\* ([0-9]+)(?:<[^>]+>)? in strace's PID NS \*/",body[returns[-1].end():])
            child=translated[1] if translated else str(returned)
            roles[child]=role
            if 'CLONE_FILES' in text:owners[child]=owner
            else:
                owners[child]=child
                members[child]=set(owned)
                for table in (sockets,connected):
                    for number in owned:
                        if (owner,number) in table:table[(child,number)]=table[(owner,number)]
        if name == 'close' and args:
            sockets.pop(key,None);connected.pop(key,None)
            owned.discard(key[1])
        if name == 'socket' and len(args) >= 2:
            if args[0]=='AF_INET6' and returned is not None and returned<0 and re.search(r'\b(?:EAFNOSUPPORT|EPERM|ENOSYS)\b',body):
                stats['blocked_ipv6_sockets']+=1
            if returned is not None and returned>=0:
                created=(owner,returned)
                owned.add(returned)
                connected.pop(created,None)
                protocol='udp' if 'SOCK_DGRAM' in args[1] else 'tcp' if 'SOCK_STREAM' in args[1] else 'other'
                if len(args)>2 and args[2] not in {'0','IPPROTO_IP','IPPROTO_TCP','IPPROTO_UDP'}:protocol='other'
                sockets[created]=(args[0],protocol)
                created_inode=socket_identity(body[returns[-1].start():])
                if created_inode:
                    inode_family[created_inode]=sockets[created]
                    inode_peer.pop(created_inode,None)
        if name == 'socketpair' and args and args[0] == 'AF_UNIX':
            for number in re.findall(r'(\d+)<UNIX', text):
                sockets[(owner,int(number))]=('AF_UNIX','local')
                owned.add(int(number))
        if name in {'accept','accept4'} and returned is not None and returned>=0:
            created=(owner,returned)
            owned.add(returned)
            connected.pop(created,None)
            destination=endpoint(args[1]) if len(args)>1 else None
            sockets[created]=sockets.get(key,(destination[0] if destination else '','tcp'))
            if destination:connected[created]=destination
            created_inode=socket_identity(body[returns[-1].start():])
            if created_inode:
                inode_family[created_inode]=sockets[created]
                if destination:inode_peer[created_inode]=destination
                else:inode_peer.pop(created_inode,None)
        if name=='getpeername' and returned==0 and len(args)>1:
            destination=endpoint(args[1])
            if destination:
                connected[key]=destination
                owned.add(key[1])
                if identity:inode_peer[identity]=destination
        if (name in {'dup','dup2','dup3'} or name=='fcntl' and len(args)>1 and args[1] in {'F_DUPFD','F_DUPFD_CLOEXEC'}) and returned is not None and returned>=0:
            duplicate=(owner,returned)
            family=sockets.get(key) or inode_family.get(identity)
            destination=connected.get(key) or inode_peer.get(identity) or inline_endpoint(args[0])
            sockets.pop(duplicate,None);connected.pop(duplicate,None)
            if family:sockets[duplicate]=family
            if destination:connected[duplicate]=destination
            if family or destination:owned.add(returned)
        if name not in {'connect', 'sendto', 'sendmsg', 'sendmmsg'}: continue
        if not args: raise ValueError('Incomplete outgoing syscall')
        family, protocol = sockets.get(key, inode_family.get(identity,('', 'udp' if '<UDP' in args[0] else 'tcp')))
        destinations = []
        if name == 'connect': destinations = [endpoint(args[1]) if len(args) > 1 else None]
        elif name == 'sendto': destinations = [endpoint(args[4]) if len(args) > 4 else None]
        elif name == 'sendmsg': destinations = [endpoint(field(args[1], 'msg_name')) if len(args) > 1 else None]
        else:
            if len(args) < 2: raise ValueError('Incomplete batched send')
            for message in arguments(args[1].strip().removeprefix('[').removesuffix(']')):
                header = field(message, 'msg_hdr')
                if header is None: raise ValueError('Unreadable batched-send header')
                destinations.append(endpoint(field(header, 'msg_name')))
        for destination in destinations:
            destination = destination or connected.get(key) or inode_peer.get(identity) or inline_endpoint(args[0])
            if destination is None and family in {'AF_UNIX', 'AF_NETLINK'}: destination = (family, '', 0)
            if destination is None:
                kind=re.search(r'<([A-Za-z0-9_-]+)',args[0])
                raise ValueError('Outgoing syscall has an unclassified destination: pid='+pid+' role='+role+
                    ' call='+name+' fd='+str(key[1])+' descriptor='+(kind[1] if kind else 'opaque'))
            if destination[0]=='AF_UNSPEC' and name!='connect':
                raise ValueError('An unspecified send destination cannot be classified')
            if name == 'connect':
                connected[key] = destination
                owned.add(key[1])
                if identity:inode_peer[identity]=destination
            if destination[0] in {'AF_UNIX', 'AF_NETLINK', 'AF_UNSPEC'}: continue
            attempts.append(Attempt(float(timestamp), role, destination[1], destination[2], protocol))
    return attempts, executed


def summarize(lines, controls, internal_addresses=(), trace_errors=''):
    if trace_errors.strip():
        raise ValueError('Tracer reported incomplete process coverage')
    stats={}
    attempts, executed = parse(lines,stats)
    if not PROCESSES.issubset(executed):
        raise ValueError('Tracer did not cover every required executable from startup')
    if {entry.get('name') for entry in controls} != set(CONTROLS) or len(controls) != len(CONTROLS):
        raise ValueError('Every process class, DNS, UDP and IPv6 control is required')
    for entry in controls:
        start, end = entry.get('start'), entry.get('end')
        if (not isinstance(start, (int,float)) or not isinstance(end,(int,float))
                or not math.isfinite(start) or not math.isfinite(end) or not 0 <= end-start <= 20):
            raise ValueError('Control interval is invalid or unbounded')
    # RFC 1918 ranges, expressed numerically so the no-host-topology gate still
    # rejects actual private addresses everywhere in committable source.
    private = [ipaddress.ip_network(value) for value in ((0x0A000000,8),(0xAC100000,12),(0xC0A80000,16),('fc00::',7))]
    permitted = {ipaddress.ip_address(value).compressed for value in internal_addresses}
    if len(permitted) > 16 or any(not any(ipaddress.ip_address(value) in network for network in private) for value in permitted):
        raise ValueError('Only bounded, exact synthetic internal addresses may be permitted')
    counts = {name:0 for name in CONTROLS}
    external = []
    for attempt in attempts:
        address = ipaddress.ip_address(attempt.address)
        # No DNS is needed in the literal-host fixture. A failed lookup sent to
        # a loopback stub must not masquerade as zero external-name attempts.
        if attempt.port!=53 and (address.is_loopback or (getattr(address,'ipv4_mapped',None) and address.ipv4_mapped.is_loopback) or attempt.address in permitted):
            continue
        matches = [entry['name'] for entry in controls if entry['start'] <= attempt.timestamp <= entry['end']
                   and CONTROLS[entry['name']] == (attempt.process,attempt.address,attempt.port,attempt.protocol)]
        if len(matches) == 1: counts[matches[0]] += 1
        else: external.append(attempt)
    if external: raise ValueError('Unapproved connection or DNS attempt observed')
    if any(count == 0 for count in counts.values()): raise ValueError('A planted external attempt escaped observation')
    return {'result':'passed','observer':'strace-network-v1','processes':sorted(PROCESSES),
            'external_attempts':0,'negative_controls':counts,'attempts_examined':len(attempts),
            'browser_driver_policy':'seccomp-deny-io-uring',**stats}
