/* A live synthetic installer must survive the controlled death of its child. */
#define _GNU_SOURCE
#include <errno.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>

static void mark(const char *value, size_t size)
{
    ssize_t written = write(4, value, size);
    if (written < 0) _exit(100 + errno);
    if (written != (ssize_t)size) _exit(71);
}

int main(void)
{
    int ready[2];
    if (!getenv("SIERX_SKIP_MARKERS")) {
        mark("sierx-installer-start\n", sizeof("sierx-installer-start\n")-1);
        mark("sierx-phase two-release-stress-1\n", sizeof("sierx-phase two-release-stress-1\n")-1);
        mark("sierx-operation start apply\n", sizeof("sierx-operation start apply\n")-1);
    }
    close(4);
    if (pipe(ready)) return 72;
    pid_t child = fork();
    if (child < 0) return 73;
    if (child == 0) {
        close(ready[1]);
        char token;
        if (read(ready[0], &token, 1) != 1) _exit(74);
        close(ready[0]);
        struct sigaction action = { .sa_handler = SIG_DFL };
        sigemptyset(&action.sa_mask);
        sigaction(SIGTERM, &action, 0);
        sigset_t mask;
        sigemptyset(&mask);
        sigaddset(&mask, SIGTERM);
        sigprocmask(SIG_UNBLOCK, &mask, 0);
        raise(SIGTERM);
        _exit(75);
    }
    close(ready[0]);
    const char *value = getenv("SIERX_PROBE_PID_WRITE_FD");
    if (!value || write(atoi(value), &child, sizeof(child)) != sizeof(child)) return 76;
    close(atoi(value));
    if (write(ready[1], "x", 1) != 1) return 77;
    close(ready[1]);
    int status;
    if (waitpid(child, &status, 0) != child) return 78;
    if (!WIFSIGNALED(status) || WTERMSIG(status) != SIGKILL) return 79;
    puts("installer-survived");
    return 0;
}
