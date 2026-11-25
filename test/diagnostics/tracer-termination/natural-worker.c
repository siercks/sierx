/* Bounded terminating-thread workload. No ptrace or error injection. */
#define _GNU_SOURCE
#include <pthread.h>
#include <sched.h>
#include <signal.h>
#include <stdatomic.h>
#include <stdio.h>
#include <sys/syscall.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>

static atomic_int ready;
static void harmless(int signal_number) { (void)signal_number; }
static void *worker(void *unused)
{
    (void)unused;
    pid_t pid=getpid(), tid=(pid_t)syscall(SYS_gettid);
    for (int i=0;i<16;i++) {
        syscall(SYS_tgkill,pid,tid,SIGUSR1);
        atomic_store_explicit(&ready,1,memory_order_release);
        sched_yield();
    }
    return 0;
}
int main(void)
{
    struct sigaction action={.sa_handler=harmless};
    sigemptyset(&action.sa_mask);
    sigaction(SIGUSR1,&action,0);
    for (int cycle=0;cycle<4096;cycle++) {
        pid_t child=fork();
        if (child<0) return 70;
        if (!child) {
            pthread_t thread;
            atomic_store(&ready,0);
            if (pthread_create(&thread,0,worker,0)) _exit(71);
            while (!atomic_load_explicit(&ready,memory_order_acquire)) sched_yield();
            for (int delay=0;delay<(cycle%8);delay++) sched_yield();
            syscall(SYS_exit_group,0);
            _exit(72);
        }
        int status;
        if (waitpid(child,&status,0)!=child || !WIFEXITED(status) || WEXITSTATUS(status)) return 73;
    }
    puts("completed=4096");
    return 0;
}
