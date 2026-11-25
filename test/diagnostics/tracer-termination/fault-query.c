/* A single, synchronized synthetic GETSIGINFO/ESRCH control; never deployed. */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <linux/audit.h>
#include <linux/filter.h>
#include <linux/seccomp.h>
#include <stddef.h>
#include <stdarg.h>
#include <stdlib.h>
#include <sys/ptrace.h>
#include <sys/prctl.h>
#include <sys/syscall.h>
#include <sys/types.h>
#include <unistd.h>

static void fail_query_for(pid_t target)
{
#if defined(__x86_64__)
    const unsigned int arch = AUDIT_ARCH_X86_64;
#elif defined(__aarch64__)
    const unsigned int arch = AUDIT_ARCH_AARCH64;
#else
#error This local control requires a supported little-endian 64-bit ABI.
#endif
    struct sock_filter filter[] = {
        BPF_STMT(BPF_LD|BPF_W|BPF_ABS, offsetof(struct seccomp_data, arch)),
        BPF_JUMP(BPF_JMP|BPF_JEQ|BPF_K, arch, 0, 7),
        BPF_STMT(BPF_LD|BPF_W|BPF_ABS, offsetof(struct seccomp_data, nr)),
        BPF_JUMP(BPF_JMP|BPF_JEQ|BPF_K, SYS_ptrace, 0, 5),
        BPF_STMT(BPF_LD|BPF_W|BPF_ABS, offsetof(struct seccomp_data, args[0])),
        BPF_JUMP(BPF_JMP|BPF_JEQ|BPF_K, PTRACE_GETSIGINFO, 0, 3),
        BPF_STMT(BPF_LD|BPF_W|BPF_ABS, offsetof(struct seccomp_data, args[1])),
        BPF_JUMP(BPF_JMP|BPF_JEQ|BPF_K, (unsigned int)target, 0, 1),
        BPF_STMT(BPF_RET|BPF_K, SECCOMP_RET_ERRNO|ESRCH),
        BPF_STMT(BPF_RET|BPF_K, SECCOMP_RET_ALLOW),
    };
    const struct sock_fprog program = { .len=sizeof(filter)/sizeof(filter[0]), .filter=filter };
    if (prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) ||
        prctl(PR_SET_SECCOMP, SECCOMP_MODE_FILTER, &program))
        _exit(80);
}

long ptrace(enum __ptrace_request request, ...)
{
    int incoming_errno = errno;
    static long (*original)(enum __ptrace_request, ...);
    static pid_t target;
    static int injected;
    int inject_this_call = 0;
    va_list args;
    va_start(args, request);
    pid_t pid = va_arg(args, pid_t);
    void *address = va_arg(args, void *);
    void *data = va_arg(args, void *);
    va_end(args);
    if (!original)
        original = dlsym(RTLD_NEXT, "ptrace");
    if (!original)
        _exit(70);
    if (!target) {
        const char *value = getenv("SIERX_PROBE_PID_READ_FD");
        if (value) {
            pid_t next;
            if (read(atoi(value), &next, sizeof(next)) == sizeof(next))
                target = next;
        }
    }
    if (!injected && target > 0 && request == PTRACE_GETSIGINFO && pid == target) {
        injected = 1;
        fail_query_for(target);
        inject_this_call = 1;
    }
    errno = incoming_errno;
    long result = original(request, pid, address, data);
    int returned_errno = errno;
    if (inject_this_call && result == -1 && returned_errno == ESRCH) {
        const char *ready = getenv("SIERX_PROBE_READY_FD");
        if (!ready || write(atoi(ready), &target, sizeof(target)) != sizeof(target))
            _exit(81);
    }
    errno = returned_errno;
    return result;
}
