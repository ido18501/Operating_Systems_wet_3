#include "segel.h"
#include "request.h"
#include "log.h"
#define MAX_QUEUE_SIZE 1024




//
// server.c: A very, very simple web server
//
// To run:
//  ./server <portnum (above 2000)>
//
// Repeatedly handles HTTP requests sent to this port number.
// Most of the work is done within routines written in request.c
//




typedef struct {
    Request *buffer;
    int capacity;
    int size;
    int front;
    int rear;
    int dequeueing_size;
    pthread_mutex_t mutex;
    pthread_cond_t not_full;
    pthread_cond_t not_empty;
} RequestQueue;
typedef struct {
    int thread_id;
    RequestQueue *queue;
} ThreadArgs;
static pthread_t *thread_pool;
static int num_threads=10;
static RequestQueue *g_queue = NULL;
static server_log g_log = NULL;
static int que_size=50;

RequestQueue* init_queue(int capacity) {
    RequestQueue *q = Malloc(sizeof(RequestQueue));
    q->buffer = Malloc(sizeof(Request) * capacity);
    q->capacity = capacity;
    q->size = 0;
    q->front = 0;
    q->rear = 0;
    q->dequeueing_size=0;
    pthread_mutex_init(&q->mutex, NULL);
    pthread_cond_init(&q->not_full, NULL);
    pthread_cond_init(&q->not_empty, NULL);
    return q;
}
void enqueue(RequestQueue *q, int connfd, struct timeval arrival_time) {
    pthread_mutex_lock(&q->mutex);
    while (q->size == q->capacity) {
        pthread_cond_wait(&q->not_full, &q->mutex);
    }
    q->buffer[q->rear].connfd = connfd;
    q->buffer[q->rear].arrival_time = arrival_time;
    q->rear = (q->rear + 1) % q->capacity;
    q->size++;
    q->dequeueing_size++;
    pthread_cond_signal(&q->not_empty);
    pthread_mutex_unlock(&q->mutex);
}


Request dequeue(RequestQueue *q, struct timeval *arrival_out, struct timeval *dispatch) {
    pthread_mutex_lock(&q->mutex);
    while (q->dequeueing_size == 0) {
        pthread_cond_wait(&q->not_empty, &q->mutex);
    }
    Request req = q->buffer[q->front];
    if (arrival_out != NULL)
        *arrival_out = req.arrival_time;
    q->front = (q->front + 1) % q->capacity;
    q->dequeueing_size--;
    gettimeofday(dispatch, NULL);
    pthread_mutex_unlock(&q->mutex);
    return req;
}
void finishHandling(RequestQueue *q){
    pthread_mutex_lock(&q->mutex);
    q->size--;
    pthread_cond_signal(&q->not_full);
    pthread_mutex_unlock(&q->mutex);
}
void *worker_thread(void *arg) {
    ThreadArgs *args = (ThreadArgs *)arg;
    int thread_id = args->thread_id;
    free(args);
    threads_stats stats = Malloc(sizeof(*stats));
    stats->id = thread_id;
    stats->stat_req = 0;
    stats->dynm_req = 0;
    stats->post_req = 0;
    stats->total_req = 0;
    while (1) {
        struct timeval arrival;
        struct timeval now, dispatch_interval;
        Request req = dequeue(g_queue, &arrival, &now);
        timersub(&now, &arrival, &dispatch_interval);
        requestHandle(req.connfd, arrival, dispatch_interval, stats, g_log);
        Close(req.connfd);
        finishHandling(g_queue);
    }

    free(stats);
    return NULL;
}


// Parses command-line arguments
void getargs(int *port, int argc, char *argv[])
{
    if (argc < 4) {
        app_error("Usage: ./server <port> <threads> <queue size>");
    }
    *port = atoi(argv[1]);
    num_threads=atoi(argv[2]);
    que_size=atoi(argv[3]);
    if(num_threads<1||que_size<1){
        app_error( "invalid parameters");
    }
}
// TODO: HW3 — Initialize thread pool and request queue
// This server currently handles all requests in the main thread.
// You must implement a thread pool (fixed number of worker threads)
// that process requests from a synchronized queue.

int main(int argc, char *argv[])
{
    int listenfd, connfd, port, clientlen;
    struct sockaddr_in clientaddr;

    getargs(&port, argc, argv);



    listenfd = Open_listenfd(port);
    //initialize que
    RequestQueue * queue=init_queue(que_size);
    //initialize thread pool
    thread_pool = Malloc(sizeof(pthread_t) * num_threads);
    // Create the global server log
    server_log log = create_log();
    //assign log and queue to globals
    g_queue = queue;
    g_log = log;
    for (int i = 0; i < num_threads; i++) {
        ThreadArgs *args = Malloc(sizeof(ThreadArgs));
        args->thread_id = i + 1;
        args->queue = queue;
        int rc = pthread_create(&thread_pool[i], NULL, worker_thread, (void*)args);
        if (rc != 0) {
            posix_error(rc, "pthread_create failed");
        }
    }


    while (1) {
        clientlen = sizeof(clientaddr);
        connfd = Accept(listenfd, (SA *)&clientaddr, (socklen_t *) &clientlen);pthread_mutex_lock(&queue->mutex);
        while (queue->size == queue->capacity) {
            pthread_cond_wait(&queue->not_full, &queue->mutex);
        }
        pthread_mutex_unlock(&queue->mutex);
        struct timeval arrival;
        gettimeofday(&arrival, NULL);
        enqueue(queue,connfd,arrival);
    }
    // Clean up the server log before exiting
    destroy_log(log);
    // TODO: HW3 — Add cleanup code for thread pool and queue
    free(queue);
    free(thread_pool);
    return 0;
}




