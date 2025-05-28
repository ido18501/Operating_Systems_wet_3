import subprocess

# Each request will run in a separate subprocess to simulate concurrency
requests = [
    ("/pageA.txt", "GET"),
    ("/pageB.txt", "GET"),
    ("/pageC.txt", "GET"),
    ("/pageA.txt", "GET"),
    ("/pageB.txt", "GET"),
    ("/pageC.txt", "POST"),  # This reads the log
]

# Store subprocesses
processes = []

for i, (filename, method) in enumerate(requests):
    p = subprocess.Popen(
        ["./client", "localhost", "8080", filename, method],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    processes.append((i + 1, p))

# Read and print outputs after all start
for thread_id, proc in processes:
    stdout, stderr = proc.communicate()
    print(f"\n=== Request {thread_id} - {requests[thread_id - 1][1]} {requests[thread_id - 1][0]} ===")
    for line in stdout.strip().split("\n"):
        print(f"[Request {thread_id}] {line}")
    if stderr:
        print(f"[Request {thread_id}][STDERR] {stderr}")

