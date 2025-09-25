#ifdef _WIN32
#include <windows.h>
#include <process.h>
#include <stdlib.h>
#include <stdio.h>

// Semaphore wrapper for Windows
typedef struct {
    HANDLE handle;
    int value;
} sem_t;

int sem_init(sem_t* sem, int pshared, unsigned int value) {
    sem->handle = CreateSemaphore(NULL, value, 0x7FFFFFFF, NULL);
    sem->value = value;
    return (sem->handle != NULL) ? 0 : -1;
}

int sem_wait(sem_t* sem) {
    DWORD result = WaitForSingleObject(sem->handle, INFINITE);
    return (result == WAIT_OBJECT_0) ? 0 : -1;
}

int sem_post(sem_t* sem) {
    BOOL result = ReleaseSemaphore(sem->handle, 1, NULL);
    return result ? 0 : -1;
}

int sem_destroy(sem_t* sem) {
    BOOL result = CloseHandle(sem->handle);
    return result ? 0 : -1;
}

// pthread wrapper for Windows
typedef HANDLE pthread_t;  // Simplified: just a handle

typedef void* (*pthread_start_routine)(void*);

typedef struct {
    pthread_start_routine start_routine;
    void* arg;
} thread_args_t;

static DWORD WINAPI thread_wrapper(LPVOID param) {
    printf("DEBUG: thread_wrapper - thread started\n");
    thread_args_t* args = (thread_args_t*)param;
    if (args && args->start_routine) {
        printf("DEBUG: thread_wrapper - calling start_routine\n");
        void* result = args->start_routine(args->arg);
        printf("DEBUG: thread_wrapper - start_routine returned\n");
        free(args);
        printf("DEBUG: thread_wrapper - thread ending\n");
        return (DWORD)(uintptr_t)result;  // Convert void* to DWORD
    }
    printf("DEBUG: thread_wrapper - invalid args, thread ending\n");
    free(args);
    return 0;
}

int pthread_create(pthread_t* thread, void* attr, pthread_start_routine start_routine, void* arg) {
    if (!thread || !start_routine) {
        printf("DEBUG: pthread_create - invalid parameters\n");
        return -1;
    }
    
    thread_args_t* args = malloc(sizeof(thread_args_t));
    if (!args) {
        printf("DEBUG: pthread_create - malloc failed\n");
        return -1;
    }
    
    args->start_routine = start_routine;
    args->arg = arg;
    
    printf("DEBUG: pthread_create - creating thread\n");
    DWORD thread_id;
    *thread = CreateThread(NULL, 0, thread_wrapper, args, 0, &thread_id);
    if (*thread == NULL) {
        printf("DEBUG: pthread_create - CreateThread failed, error: %lu\n", GetLastError());
        free(args);
        return -1;
    }
    
    printf("DEBUG: pthread_create - thread created successfully, handle: %p, id: %lu\n", *thread, thread_id);
    return 0;
}

int pthread_join(pthread_t thread, void** retval) {
    printf("DEBUG: pthread_join - joining thread handle: %p\n", thread);
    
    if (thread == NULL) {
        printf("DEBUG: pthread_join - invalid thread handle\n");
        return -1;
    }
    
    printf("DEBUG: pthread_join - waiting for thread to complete\n");
    DWORD result = WaitForSingleObject(thread, INFINITE);
    printf("DEBUG: pthread_join - WaitForSingleObject returned: %lu\n", result);
    
    CloseHandle(thread);
    
    if (retval) {
        *retval = NULL;  // We don't support return values yet
    }
    
    printf("DEBUG: pthread_join - thread joined successfully\n");
    return (result == WAIT_OBJECT_0) ? 0 : -1;
}

// Simple barrier implementation for Windows
typedef struct {
    CRITICAL_SECTION lock;
    CONDITION_VARIABLE cond;
    unsigned count;      // number of threads required to pass the barrier
    unsigned waiting;    // number of threads currently waiting
    unsigned generation; // generation counter to avoid spurious wakeups
} pthread_barrier_t;

int pthread_barrier_init(pthread_barrier_t* barrier, void* attr, unsigned count) {
    (void)attr; // unused
    if (!barrier || count == 0) return -1;
    InitializeCriticalSection(&barrier->lock);
    InitializeConditionVariable(&barrier->cond);
    barrier->count = count;
    barrier->waiting = 0;
    barrier->generation = 0;
    return 0;
}

int pthread_barrier_wait(pthread_barrier_t* barrier) {
    if (!barrier) return -1;
    EnterCriticalSection(&barrier->lock);
    unsigned gen = barrier->generation;
    barrier->waiting++;
    if (barrier->waiting >= barrier->count) {
        barrier->generation++;
        barrier->waiting = 0;
        WakeAllConditionVariable(&barrier->cond);
        LeaveCriticalSection(&barrier->lock);
        return 0;
    }
    while (gen == barrier->generation) {
        SleepConditionVariableCS(&barrier->cond, &barrier->lock, INFINITE);
    }
    LeaveCriticalSection(&barrier->lock);
    return 0;
}

int pthread_barrier_destroy(pthread_barrier_t* barrier) {
    if (!barrier) return -1;
    DeleteCriticalSection(&barrier->lock);
    // CONDITION_VARIABLE does not need explicit destruction
    return 0;
}

#endif // _WIN32
