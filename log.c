#include <stdlib.h>
#include <string.h>
#include "log.h"
#include "segel.h"


// Creates a new server log instance (stub)
server_log create_log() {
    server_log log = Malloc(sizeof(*log));
    log->capacity = 4096;
    log->size = 0;
    log->buffer = Malloc(log->capacity);
    log->buffer[0] = '\0';

    pthread_mutex_init(&log->lock, NULL);
    pthread_cond_init(&log->readers_cond, NULL);
    pthread_cond_init(&log->writers_cond, NULL);

    log->readers = 0;
    log->writers = 0;
    log->waiting_writers = 0;

    return log;
}


// Destroys and frees the log (stub)
void destroy_log(server_log log) {
    if (!log) {
        return;
    }
    pthread_mutex_destroy(&log->lock);
    pthread_cond_destroy(&log->readers_cond);
    pthread_cond_destroy(&log->writers_cond);
    free(log->buffer);
    free(log);
}

static void log_start_read(server_log log) {
    pthread_mutex_lock(&log->lock);
    while (log->writers > 0 || log->waiting_writers > 0) {
        pthread_cond_wait(&log->readers_cond, &log->lock);
    }
    log->readers++;
    pthread_mutex_unlock(&log->lock);
}

static void log_end_read(server_log log) {
    pthread_mutex_lock(&log->lock);
    log->readers--;
    if (log->readers == 0) {
        pthread_cond_signal(&log->writers_cond);
    }
    pthread_mutex_unlock(&log->lock);
}

static void log_start_write(server_log log) {
    pthread_mutex_lock(&log->lock);
    log->waiting_writers++;
    while (log->readers > 0 || log->writers > 0) {
        pthread_cond_wait(&log->writers_cond, &log->lock);
    }
    log->waiting_writers--;
    log->writers = 1;
    pthread_mutex_unlock(&log->lock);
}

static void log_end_write(server_log log) {
    pthread_mutex_lock(&log->lock);
    log->writers = 0;
    if (log->waiting_writers > 0) {
        pthread_cond_signal(&log->writers_cond);
    } else {
        pthread_cond_broadcast(&log->readers_cond);
    }
    pthread_mutex_unlock(&log->lock);
}

// Returns dummy log content as string (stub)
int get_log(server_log log, char **dst) {
    if (!log || !dst) {
        return 0;
    }

    log_start_read(log);
    *dst = Malloc(log->size + 1);
    memcpy(*dst, log->buffer, log->size + 1);
    int result_size = log->size;
    log_end_read(log);
    return result_size;
}


// Appends a new entry to the log (no-op stub)
void add_to_log(server_log log, const char *data, int data_len) {
    if (!log || !data || data_len <= 0) {
        return;
    }

    log_start_write(log);

    pthread_mutex_lock(&log->lock);

    if (log->size + data_len + 1 >= log->capacity) {
        size_t new_capacity = log->capacity * 2;
        while (new_capacity < log->size + data_len + 1) {
            new_capacity *= 2;
        }
        char *new_buf = Malloc(new_capacity);
        memcpy(new_buf, log->buffer, log->size);
        free(log->buffer);
        log->buffer = new_buf;
        log->capacity = new_capacity;
    }

    memcpy(log->buffer + log->size, data, data_len);
    log->size += data_len;
    log->buffer[log->size] = '\0';

    pthread_mutex_unlock(&log->lock);

    log_end_write(log);
}

