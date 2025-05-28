import subprocess
import threading
import time

def run_reader(req_id):
    print(f"=== Reader {req_id} - POST /pageC.txt ===")
    result = subprocess.run(["./client", "localhost", "8080", "/pageC.txt", "POST"], capture_output=True, text=True)
    for line in result.stdout.splitlines():
        print(f"[Reader {req_id}] {line}")

# Launch multiple reader threads at the same time
threads = []
num_readers = 4  # You can increase to 5–10 if you want to stress more

for i in range(1, num_readers + 1):
    t = threading.Thread(target=run_reader, args=(i,))
    threads.append(t)
    t.start()

for t in threads:
    t.join()
