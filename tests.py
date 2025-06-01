#!/usr/bin/env python3
import os, sys, time, signal, socket, random, subprocess, threading, psutil
from collections import namedtuple, Counter

# ───────── pretty colours ─────────
try:
    from colorama import init, Fore, Style
    init()
    GREEN, RED, YEL, DIM, RST = Fore.GREEN, Fore.RED, Fore.YELLOW, Style.DIM, Style.RESET_ALL
except ImportError:
    GREEN = RED = YEL = DIM = RST = ""

SERVER_BIN = "./server"
CLIENT_BIN = "./client"
if not (os.path.isfile(SERVER_BIN) and os.path.isfile(CLIENT_BIN)):
    sys.exit(f"{RED}Error: ./server or ./client not found{RST}")

BASE_PORT = 9000
_used = set()

def next_port() -> str:
    while True:
        p = random.randint(BASE_PORT, 60000)
        if p not in _used:
            _used.add(p)
            return str(p)

def wait_for_port(port: str, timeout=3.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        with socket.socket() as s:
            s.settimeout(0.30)
            result = s.connect_ex(("127.0.0.1", int(port)))
            if result == 0:
                print(f"{GREEN}[*] Port {port} is accepting connections{RST}")
                return True
            else:
                print(f"{DIM}[.] Waiting for port {port}... result={result}{RST}")
        time.sleep(0.05)
    return False

def start_server(port, pool, queue):
    print(f"{YEL}[*] Starting server on port {port} with pool={pool}, queue={queue}{RST}")
    print(f"[DEBUG] Launching server with args: {SERVER_BIN} {port} {pool} {queue}")
    proc = subprocess.Popen(
        [SERVER_BIN, port, str(pool), str(queue)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        preexec_fn=os.setsid
    )
    time.sleep(0.5)
    proc.poll()
    if proc.returncode is not None:
        print(f"{RED}[!] Server exited early! Return code: {proc.returncode}{RST}")
        err = proc.stderr.read().decode().strip()
        print(f"{RED}[!] Server stderr:\n{err}{RST}")
    server_ps = psutil.Process(proc.pid)
    ready = wait_for_port(port, 3.0)
    if not ready:
        print(f"{RED}[!] Server did not bind to port {port} in time.{RST}")
        err = proc.stderr.read().decode().strip()
        print(f"{RED}[!] Server stderr:\n{err}{RST}")
    elif not server_ps.is_running():
        print(f"{RED}[!] Server crashed before handling any client!{RST}")
    return proc, ready

def kill_server(proc):
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGINT)
        proc.wait(timeout=2)
    except Exception:
        proc.kill()

def run_one_client(host, port, file_, method, bucket, idx):
    cp = subprocess.run([CLIENT_BIN, host, port, file_, method],
                        capture_output=True, text=True, timeout=6)
    bucket[idx] = cp

def run_clients(reqs, port):
    outs = [None] * len(reqs)
    th = []

    def run_and_log(i, fn, m):
        print(f"{DIM}    [*] Launching client {i}: {m} {fn}{RST}")
        run_one_client("localhost", port, fn, m, outs, i)

    for i, (fn, m) in enumerate(reqs):
        t = threading.Thread(target=run_and_log, args=(i, fn, m), daemon=True)
        th.append(t)
        t.start()
    for t in th:
        t.join()
    return outs

def good_status(cp, allow_404=False):
    if cp.returncode != 0:
        return False

    lines = cp.stdout.splitlines()
    for line in lines:
        if "HTTP/1." in line:
            if "200 OK" in line:
                return True
            if allow_404 and ("404" in line or "Not found" in line):
                return True
            return False
    return False


REQS = dict(
    GET_A = ("/pageA.txt", "GET"),
    GET_B = ("/pageB.txt", "GET"),
    GET_C = ("/pageC.txt", "GET"),
    MISS_G= ("/nope.txt",  "GET"),
    POST_L= ("/pageC.txt", "POST"),
    MISS_P= ("/nope.txt",  "POST"),
)

def repeat(r, n): return [r] * n
def mix(*keys):   return [REQS[k] for k in keys]

Case = namedtuple("Case", "label pool queue nreq gen")
Result = namedtuple("Result", "label ok reason")

cases = [
    Case("T01 concurrent readers",        4,  8,  6, repeat(REQS["POST_L"], 6)),
    Case("T02 single-thread burst",       1, 20, 10, repeat(REQS["GET_A"], 10)),
    Case("T03 queue overflow",            2,  2,  8, repeat(REQS["GET_B"], 8)),
    Case("T04 mix static & log",          3, 10,  7, mix("GET_A","GET_B","POST_L","GET_C","GET_A","POST_L","POST_L")),
    Case("T05 many threads small queue", 10,  1,  5, repeat(REQS["GET_C"], 5)),
    Case("T06 heavy readers 20×",        10, 20, 20, repeat(REQS["POST_L"], 20)),
    Case("T07 missing file GET",          2,  5,  1, repeat(REQS["MISS_G"], 1)),
    Case("T08 missing file POST",         2,  5,  1, repeat(REQS["MISS_P"], 1)),
    Case("T09 alt GET/POST 12×",          4, 12, 12, sum([[REQS["GET_A"], REQS["POST_L"]] for _ in range(6)], [])),
    Case("T10 tiny queue one thread",     1,  1,  3, repeat(REQS["GET_B"], 3)),
    Case("T11 stress 30 mixed",           6, 15, 30, [random.choice(list(REQS.values())) for _ in range(30)]),
    Case("T12 fairness read/write",       2, 10, 10, mix("GET_A","GET_B","POST_L","POST_L","GET_C","POST_L","GET_A","POST_L","POST_L","GET_B")),
    Case("T13 queue == pool",             4,  4,  8, repeat(REQS["GET_C"], 8)),
    Case("T14 long queue small pool",     2, 15, 12, repeat(REQS["GET_A"], 12)),
    Case("T15 write heavy",               5, 10, 15, repeat(REQS["GET_B"], 15)),
    Case("T16 read heavy small pool",     2,  8, 10, repeat(REQS["POST_L"], 10)),
    Case("T17 zero-log then POST",        3,  6,  1, repeat(REQS["POST_L"], 1)),
    Case("T18 interleaved miss/good",     3,  6,  6, mix("GET_A","MISS_G","POST_L","MISS_P","GET_B","POST_L")),
    Case("T19 large queue single writer", 1, 30, 25, repeat(REQS["GET_A"], 25)),
    Case("T20 many pools tiny queue",    12,  1, 12, repeat(REQS["GET_B"], 12)),
    Case("T21 50 log readers",           10, 20, 50, repeat(REQS["POST_L"], 50)),
]

MISS_CASES = {REQS["MISS_G"], REQS["MISS_P"]}
results = []
for c in cases:
    port = next_port()
    srv, up = start_server(port, c.pool, c.queue)

    if not up:
        err = srv.stderr.read().decode().strip()
        results.append(Result(c.label, False, err or "server failed to bind"))
        kill_server(srv)
        continue

    try:
        outs = run_clients(c.gen, port)
        allow_404 = any(r in MISS_CASES for r in c.gen)
        ok = all(good_status(cp, allow_404) for cp in outs)
        if ok:
            reason = "all clients OK"
        else:
            bad = next(cp for cp in outs if not good_status(cp, allow_404))
            print(f"{RED}[!] Failed client output:{RST}")
            print(f"{DIM}{bad.stdout}{RST}")
            print(f"{RED}{bad.stderr}{RST}")
            reason = (bad.stderr.strip()
                      or next((l for l in bad.stdout.splitlines() if l.startswith("HTTP/")), "no HTTP status"))
            if srv.poll() is not None:
                reason += f" | server exited with code {srv.returncode}"
                stderr_dump = srv.stderr.read().decode().strip()
                if stderr_dump:
                    print(f"{RED}[!] Server stderr:\n{stderr_dump}{RST}")
    except Exception as e:
        ok, reason = False, f"Exception {e}"
    finally:
        kill_server(srv)

    results.append(Result(c.label, ok, reason))

width = max(len(r.label) for r in results) + 2
print("\n" + "=" * width)
for r in results:
    tag = f"{GREEN}PASS{RST}" if r.ok else f"{RED}FAIL{RST}"
    print(f"{r.label:<{width}} {tag}  {DIM}{r.reason}{RST}")
print("=" * width)
tot = Counter(r.ok for r in results)
print(f"\nTotal: {tot[True]} passed, {tot[False]} failed out of {len(results)} cases.")
if not GREEN:
    print("Tip:  pip install colorama  for coloured output")

