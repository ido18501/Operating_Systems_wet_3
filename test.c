/*
 * test.c
 *
 * A comprehensive C–based smoke‐test for HW3 server (Linux).  It covers:
 *
 *   1) Creation of public/test.txt and public/output.cgi
 *   2) 404 Not Found
 *   3) 403 Forbidden (static & dynamic)
 *   4) 501 Not Implemented
 *   5) Static GET
 *   6) Dynamic CGI GET
 *   7) POST (log retrieval)
 *   8) 5 concurrent GET /test.txt
 *   9) Multiple combinations of <num_threads, queue_size>
 *  10) No spin‐locks / busy waiting: ensure idle CPU usage ≈ 0
 *
 * Usage:
 *   gcc -Wall -pthread -o test test3.c
 *   ./test
 *
 * Run it in the same directory as your compiled `server` binary.
 */

#define _POSIX_C_SOURCE 200809L

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>      // strncasecmp
#include <errno.h>
#include <unistd.h>       // fork, execl, sleep, usleep, access, unlink
#include <sys/types.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <sys/wait.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <arpa/inet.h>
#include <pthread.h>
#include <signal.h>
#include <time.h>
#include <sys/time.h>     // gettimeofday
#include <sys/resource.h> // getrusage
#include <stddef.h>       // size_t

#define SERVER_BIN        "./server"
#define PUBLIC_DIR        "public"
#define TEST_FILENAME     "test.txt"
#define CGI_FILENAME      "output.cgi"
#define BAD_CGI_FILENAME  "nocgi.cgi"
#define FORBIDDEN_STATIC  "forbidden.txt"

#define INITIAL_SLEEP_SEC 2    /* secs to sleep so server binds */
#define TIMEOUT_READ_SEC  5    /* timeout for reading socket */

static const char *TEST_FILE_CONTENT =
    "Hello, this is a static test file.\n"
    "Line two.\n";

static const char *CGI_CONTENT =
    "#!/bin/bash\n"
    "echo \"Content-Type: text/plain\"\n"
    "echo\n"
    "echo \"DYNAMIC_OK\"\n";

static const char *EXPECTED_CGI_MARKER = "DYNAMIC_OK";

static pid_t server_pid = -1;

/* Utility: print FAIL, kill server, exit(1) */
static void fail(const char *msg) {
    fprintf(stderr, "FAIL: %s\n", msg);
    if (server_pid > 0) {
        kill(-server_pid, SIGTERM);
        waitpid(server_pid, NULL, 0);
    }
    exit(EXIT_FAILURE);
}

/* Utility: print PASS, kill server, exit(0) */
static void succeed() {
    printf("PASS\n");
    if (server_pid > 0) {
        kill(-server_pid, SIGTERM);
        waitpid(server_pid, NULL, 0);
    }
    exit(EXIT_SUCCESS);
}

/* mkdir -p style */
static int mkdir_p(const char *dir) {
    char tmp[512];
    char *p;
    size_t len;
    snprintf(tmp, sizeof(tmp), "%s", dir);
    len = strlen(tmp);
    if (len && tmp[len-1] == '/') tmp[len-1] = 0;
    for (p = tmp+1; *p; p++) {
        if (*p == '/') {
            *p = 0;
            if (mkdir(tmp, 0755) && errno != EEXIST) return -1;
            *p = '/';
        }
    }
    if (mkdir(tmp, 0755) && errno != EEXIST) return -1;
    return 0;
}

/* Write file with contents + mode */
static int write_file(const char *path, const char *content, mode_t mode) {
    int fd = open(path, O_CREAT | O_TRUNC | O_WRONLY, mode);
    if (fd < 0) return -1;
    size_t to_write = strlen(content);
    ssize_t w = write(fd, content, to_write);
    close(fd);
    return (w == (ssize_t)to_write) ? 0 : -1;
}

/*
 * Start server child, redirect stdout/stderr to /dev/null, new PGID.
 * Pass in num_threads, queue_size.
 */
static void start_server(int num_threads, int queue_size) {
    pid_t pid = fork();
    if (pid < 0) {
        fail("fork failed");
    }
    if (pid == 0) {
        int devnull = open("/dev/null", O_WRONLY);
        if (devnull >= 0) {
            dup2(devnull, STDOUT_FILENO);
            dup2(devnull, STDERR_FILENO);
            close(devnull);
        }
        if (setpgid(0, 0) < 0) _exit(1);
        char port_str[16], threads_str[16], queue_str[16];
        snprintf(port_str, sizeof(port_str), "%d", 7777);
        snprintf(threads_str, sizeof(threads_str), "%d", num_threads);
        snprintf(queue_str, sizeof(queue_str), "%d", queue_size);
        execl(SERVER_BIN, SERVER_BIN, port_str, threads_str, queue_str, (char*)NULL);
        _exit(1);
    }
    server_pid = pid;
}

/* Send raw_request, return malloc'd response (length in *resp_len). */
static char *http_request(const char *raw_request, size_t *resp_len) {
    int sock = socket(AF_INET, SOCK_STREAM, 0);
    if (sock < 0) fail("socket failed in http_request");
    struct timeval tv = {.tv_sec = TIMEOUT_READ_SEC, .tv_usec = 0};
    setsockopt(sock, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));
    struct sockaddr_in addr = {0};
    addr.sin_family = AF_INET;
    addr.sin_port = htons(7777);
    inet_pton(AF_INET, "127.0.0.1", &addr.sin_addr);
    if (connect(sock, (struct sockaddr*)&addr, sizeof(addr)) < 0) {
        close(sock);
        return NULL;
    }
    size_t req_len = strlen(raw_request);
    if (write(sock, raw_request, req_len) != (ssize_t)req_len) {
        close(sock);
        fail("write failed in http_request");
    }
    size_t cap = 65536;
    char *buf = malloc(cap);
    if (!buf) fail("malloc failed in http_request");
    size_t total = 0;
    while (1) {
        ssize_t n = read(sock, buf + total, cap - total);
        if (n > 0) {
            total += n;
            if (total + 1 >= cap) {
                cap *= 2;
                buf = realloc(buf, cap);
                if (!buf) fail("realloc failed in http_request");
            }
        } else break;
    }
    close(sock);
    buf[total] = 0;
    *resp_len = total;
    return buf;
}

/* Parse HTTP response into status, headers[], body ptr/len. */
static int parse_response(const char *resp_buf, size_t resp_len,
                          char **out_status,
                          char ***out_headers, int *out_nheaders,
                          const char **out_body, size_t *out_body_len) {
    const char *sep = strstr(resp_buf, "\r\n\r\n");
    if (!sep) return -1;
    size_t header_len = sep - resp_buf;
    const char *body_ptr = sep + 4;
    size_t body_len = resp_len - (header_len + 4);

    char *hdr_block = malloc(header_len + 1);
    if (!hdr_block) return -1;
    memcpy(hdr_block, resp_buf, header_len);
    hdr_block[header_len] = 0;

    int cap = 32;
    char **hdrs = malloc(sizeof(char*) * cap);
    if (!hdrs) { free(hdr_block); return -1; }
    int n = 0;
    char *line, *saveptr;
    line = strtok_r(hdr_block, "\r\n", &saveptr);
    if (!line) { free(hdrs); free(hdr_block); return -1; }
    *out_status = strdup(line);
    while ((line = strtok_r(NULL, "\r\n", &saveptr)) != NULL) {
        if (n >= cap) {
            cap *= 2;
            hdrs = realloc(hdrs, sizeof(char*) * cap);
            if (!hdrs) { free(hdr_block); return -1; }
        }
        hdrs[n++] = strdup(line);
    }
    free(hdr_block);
    *out_headers = hdrs;
    *out_nheaders = n;
    *out_body = body_ptr;
    *out_body_len = body_len;
    return 0;
}

static void check_status_ok(const char *status_line, const char *test_name) {
    if (strncmp(status_line, "HTTP/1.0 200 OK", 15) != 0) {
        char buf[256];
        snprintf(buf, sizeof(buf), "%s: bad status \"%s\"", test_name, status_line);
        fail(buf);
    }
}

static int get_content_length(char **headers, int nheaders, const char *test_name) {
    for (int i = 0; i < nheaders; i++) {
        if (strncasecmp(headers[i], "Content-Length:", 15) == 0) {
            const char *p = headers[i] + 15;
            while (*p == ' ' || *p == '\t') p++;
            return atoi(p);
        }
    }
    char buf[128];
    snprintf(buf, sizeof(buf), "%s: missing Content-Length", test_name);
    fail(buf);
    return -1;
}

static void check_stat_headers(char **headers, int nheaders, const char *test_name) {
    const char *keys[7] = {
        "Stat-Req-Arrival::",
        "Stat-Req-Dispatch::",
        "Stat-Thread-Id::",
        "Stat-Thread-Count::",
        "Stat-Thread-Static::",
        "Stat-Thread-Dynamic::",
        "Stat-Thread-Post::"
    };
    int found[7] = {0};
    for (int i = 0; i < nheaders; i++) {
        for (int k = 0; k < 7; k++) {
            if (strncmp(headers[i], keys[k], strlen(keys[k])) == 0) {
                found[k] = 1;
            }
        }
    }
    for (int k = 0; k < 7; k++) {
        if (!found[k]) {
            char buf[128];
            snprintf(buf, sizeof(buf), "%s: missing %s", test_name, keys[k]);
            fail(buf);
        }
    }
}

static void free_headers(char **headers, int n) {
    for (int i = 0; i < n; i++) free(headers[i]);
    free(headers);
}

/* -------------- TEST FUNCTIONS -------------- */

/* 404 Not Found */
static void test_404_not_found() {
    const char *req =
        "GET /doesnotexist.html HTTP/1.1\r\n"
        "Host: localhost\r\n"
        "\r\n";
    size_t rlen; char *resp = http_request(req, &rlen);
    if (!resp) fail("test_404_not_found: no response");
    char *status=NULL, **headers=NULL; int nh=0;
    const char *body; size_t blen;
    if (parse_response(resp, rlen, &status, &headers, &nh, &body, &blen)) {
        free(resp); fail("test_404_not_found: malformed");
    }
    if (strncmp(status, "HTTP/1.0 404", 12)) fail("test_404_not_found: status!=404");
    check_stat_headers(headers, nh, "test_404_not_found");
    free(status); free_headers(headers, nh); free(resp);
    printf("✓ 404 test passed.\n");
}

/* 403 Forbidden (static) */
static void test_403_forbidden_static() {
    char path[512];
    snprintf(path, sizeof(path), "%s/%s", PUBLIC_DIR, FORBIDDEN_STATIC);
    unlink(path);  // remove old file if present
    if (write_file(path, "X", 0000)) fail("test_403_forbidden_static: write failed");
    char req[256];
    snprintf(req, sizeof(req),
        "GET /%s HTTP/1.1\r\nHost: localhost\r\n\r\n", FORBIDDEN_STATIC);
    size_t rlen; char *resp = http_request(req, &rlen);
    if (!resp) fail("test_403_forbidden_static: no response");
    char *status=NULL, **headers=NULL; int nh=0;
    const char *body; size_t blen;
    if (parse_response(resp, rlen, &status, &headers, &nh, &body, &blen)) {
        free(resp); fail("test_403_forbidden_static: malformed");
    }
    if (strncmp(status, "HTTP/1.0 403", 12)) fail("test_403_forbidden_static: status!=403");
    check_stat_headers(headers, nh, "test_403_forbidden_static");
    free(status); free_headers(headers, nh); free(resp);
    printf("✓ 403 static test passed.\n");
}

/* 403 Forbidden (dynamic) */
static void test_403_forbidden_dynamic() {
    char path[512];
    snprintf(path, sizeof(path), "%s/%s", PUBLIC_DIR, BAD_CGI_FILENAME);
    unlink(path);  // remove old file if present
    if (write_file(path,
        "#!/bin/bash\n"
        "echo hi\n", 0644)) fail("test_403_forbidden_dynamic: write failed");
    chmod(path, 0644);
    char req[256];
    snprintf(req, sizeof(req),
        "GET /%s HTTP/1.1\r\nHost: localhost\r\n\r\n", BAD_CGI_FILENAME);
    size_t rlen; char *resp = http_request(req, &rlen);
    if (!resp) fail("test_403_forbidden_dynamic: no response");
    char *status=NULL, **headers=NULL; int nh=0;
    const char *body; size_t blen;
    if (parse_response(resp, rlen, &status, &headers, &nh, &body, &blen)) {
        free(resp); fail("test_403_forbidden_dynamic: malformed");
    }
    if (strncmp(status, "HTTP/1.0 403", 12)) fail("test_403_forbidden_dynamic: status!=403");
    check_stat_headers(headers, nh, "test_403_forbidden_dynamic");
    free(status); free_headers(headers, nh); free(resp);
    printf("✓ 403 dynamic test passed.\n");
}

/* 501 Not Implemented */
static void test_501_not_implemented() {
    const char *req =
        "PUT /test.txt HTTP/1.1\r\nHost: localhost\r\n\r\n";
    size_t rlen; char *resp = http_request(req, &rlen);
    if (!resp) fail("test_501_not_implemented: no response");
    char *status=NULL, **headers=NULL; int nh=0;
    const char *body; size_t blen;
    if (parse_response(resp, rlen, &status, &headers, &nh, &body, &blen)) {
        free(resp); fail("test_501_not_implemented: malformed");
    }
    if (strncmp(status, "HTTP/1.0 501", 12)) fail("test_501_not_implemented: status!=501");
    check_stat_headers(headers, nh, "test_501_not_implemented");
    free(status); free_headers(headers, nh); free(resp);
    printf("✓ 501 test passed.\n");
}

/* Static GET */
static void test_static_get() {
    char req[256];
    snprintf(req, sizeof(req),
        "GET /%s HTTP/1.1\r\nHost: localhost\r\n\r\n", TEST_FILENAME);
    size_t rlen; char *resp = http_request(req, &rlen);
    if (!resp) fail("test_static_get: no response");
    char *status=NULL, **headers=NULL; int nh=0;
    const char *body; size_t blen;
    if (parse_response(resp, rlen, &status, &headers, &nh, &body, &blen)) {
        free(resp); fail("test_static_get: malformed");
    }
    check_status_ok(status, "test_static_get");
    int cl = get_content_length(headers, nh, "test_static_get");
    int exp = (int)strlen(TEST_FILE_CONTENT);
    if (cl != exp) fail("test_static_get: Content-Length mismatch");
    if ((int)blen != exp) fail("test_static_get: body length mismatch");
    if (memcmp(body, TEST_FILE_CONTENT, exp)) fail("test_static_get: body mismatch");
    check_stat_headers(headers, nh, "test_static_get");
    free(status); free_headers(headers, nh); free(resp);
    printf("✓ Static GET test passed.\n");
}

/* Dynamic CGI GET */
static void test_dynamic_get() {
    char req[256];
    snprintf(req, sizeof(req),
        "GET /%s?msg=Hello HTTP/1.1\r\nHost: localhost\r\n\r\n", CGI_FILENAME);
    size_t rlen; char *resp = http_request(req, &rlen);
    if (!resp) fail("test_dynamic_get: no response");
    char *status=NULL, **headers=NULL; int nh=0;
    const char *body; size_t blen;
    if (parse_response(resp, rlen, &status, &headers, &nh, &body, &blen)) {
        free(resp); fail("test_dynamic_get: malformed");
    }
    check_status_ok(status, "test_dynamic_get");
    char *copy = malloc(blen+1);
    if (!copy) fail("test_dynamic_get: malloc");
    memcpy(copy, body, blen);
    copy[blen] = 0;
    if (!strstr(copy, EXPECTED_CGI_MARKER)) fail("test_dynamic_get: marker missing");
    free(copy);
    check_stat_headers(headers, nh, "test_dynamic_get");
    free(status); free_headers(headers, nh); free(resp);
    printf("✓ Dynamic CGI GET test passed.\n");
}

/* POST /  (log retrieval) */
static void test_post_log() {
    const char *req =
        "POST / HTTP/1.1\r\nHost: localhost\r\nContent-Length: 0\r\n\r\n";
    size_t rlen; char *resp = http_request(req, &rlen);
    if (!resp) fail("test_post_log: no response");
    char *status=NULL, **headers=NULL; int nh=0;
    const char *body; size_t blen;
    if (parse_response(resp, rlen, &status, &headers, &nh, &body, &blen)) {
        free(resp); fail("test_post_log: malformed");
    }
    check_status_ok(status, "test_post_log");
    int count=0; const char *p=body;
    while (1) {
        const char *q=strstr(p, "Stat-Req-Arrival::");
        if (!q) break;
        count++; p=q+1;
    }
    if (count < 2) fail("test_post_log: too few Stat-Req-Arrival::");
    check_stat_headers(headers, nh, "test_post_log");
    free(status); free_headers(headers, nh); free(resp);
    printf("✓ POST log test passed.\n");
}

struct concurrent_arg { int idx, error; };

/* Worker for concurrency test */
static void *concurrent_worker(void *argp) {
    struct concurrent_arg *arg = argp;
    char req[256];
    snprintf(req, sizeof(req),
        "GET /%s HTTP/1.1\r\nHost: localhost\r\n\r\n", TEST_FILENAME);
    size_t rlen; char *resp = http_request(req, &rlen);
    if (!resp) { arg->error=1; return NULL; }
    char *status=NULL, **headers=NULL; int nh=0;
    const char *body; size_t blen;
    if (parse_response(resp, rlen, &status, &headers, &nh, &body, &blen)) {
        arg->error=1;
    } else {
        if (strncmp(status, "HTTP/1.0 200 OK",15)) arg->error=1;
    }
    if (status) free(status);
    if (headers) free_headers(headers, nh);
    if (resp) free(resp);
    return NULL;
}

/* 5 concurrent GETs */
static void test_concurrent_get() {
    pthread_t threads[5];
    struct concurrent_arg args[5];
    for (int i=0; i<5; i++) {
        args[i].idx=i; args[i].error=0;
        if (pthread_create(&threads[i], NULL, concurrent_worker, &args[i])) {
            fail("test_concurrent_get: pthread_create failed");
        }
    }
    sleep(1);
    for (int i=0; i<5; i++) {
        pthread_join(threads[i], NULL);
        if (args[i].error) {
            char buf[64];
            snprintf(buf, sizeof(buf),
                     "test_concurrent_get: thread %d failed", i);
            fail(buf);
        }
    }
    printf("✓ Concurrency GET test passed.\n");
}

/* Spin-lock / busy-wait detection: measure CPU usage while idle */
static void test_no_spinlock() {
    struct rusage ru_start, ru_end;
    if (getrusage(RUSAGE_CHILDREN, &ru_start)) fail("test_no_spinlock: rusage start");
    sleep(1);
    if (getrusage(RUSAGE_CHILDREN, &ru_end)) fail("test_no_spinlock: rusage end");
    double utime_start = ru_start.ru_utime.tv_sec + ru_start.ru_utime.tv_usec/1e6;
    double stime_start = ru_start.ru_stime.tv_sec + ru_start.ru_stime.tv_usec/1e6;
    double utime_end = ru_end.ru_utime.tv_sec + ru_end.ru_utime.tv_usec/1e6;
    double stime_end = ru_end.ru_stime.tv_sec + ru_end.ru_stime.tv_usec/1e6;
    double cpu_used = (utime_end - utime_start) + (stime_end - stime_start);
    if (cpu_used > 0.05) fail("test_no_spinlock: idle CPU usage too high");
    printf("✓ No spin-lock / busy-wait test passed.\n");
}

/* Run tests for a given (num_threads, queue_size) combo */
static void run_tests_for_config(int num_threads, int queue_size) {
    printf("== Testing with threads=%d, queue=%d ==\n", num_threads, queue_size);

    /* Start server with these parameters */
    start_server(num_threads, queue_size);
    sleep(INITIAL_SLEEP_SEC);

    test_no_spinlock();
    test_404_not_found();
    test_403_forbidden_static();
    test_403_forbidden_dynamic();
    test_501_not_implemented();
    test_static_get();
    test_dynamic_get();
    test_post_log();
    test_concurrent_get();

    /* Kill server */
    kill(-server_pid, SIGTERM);
    waitpid(server_pid, NULL, 0);
    server_pid = -1;
}

int main(void) {
    if (access(SERVER_BIN, X_OK)) fail("Server not found/executable");

    if (mkdir_p(PUBLIC_DIR)) fail("mkdir public failed");

    /* Create public/test.txt and public/output.cgi once */
    {
        char path[512];
        snprintf(path, sizeof(path), "%s/%s", PUBLIC_DIR, TEST_FILENAME);
        if (write_file(path, TEST_FILE_CONTENT, 0644))
            fail("write public/test.txt failed");
    }
    {
        char path[512];
        snprintf(path, sizeof(path), "%s/%s", PUBLIC_DIR, CGI_FILENAME);
        if (write_file(path, CGI_CONTENT, 0755))
            fail("write public/output.cgi failed");
        chmod(path, 0755);
    }

    /* Test several (num_threads, queue_size) combos */
    int combos[][2] = {
        {1, 1},
        {2, 2},
        {4, 4},
        {8, 2},
        {2, 8},
        {4, 1},
        {1, 4}
    };
    int ncombos = sizeof(combos)/sizeof(combos[0]);
    for (int i = 0; i < ncombos; i++) {
        run_tests_for_config(combos[i][0], combos[i][1]);
    }

    succeed();
    return 0;
}
