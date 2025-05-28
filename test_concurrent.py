import subprocess
import threading

def run_client(filename, method):
    subprocess.run(["./client", "localhost", "8080", filename, method])

# Create multiple client threads
threads = []
requests = [
    ("/pageA.txt", "GET"),
    ("/pageB.txt", "GET"),
    ("/pageC.txt", "GET"),
    ("/pageA.txt", "GET"),
    ("/pageB.txt", "GET"),
    ("/pageC.txt", "POST"),  # This will read the log
]

for filename, method in requests:
    t = threading.Thread(target=run_client, args=(filename, method))
    threads.append(t)
    t.start()

for t in threads:
    t.join()
