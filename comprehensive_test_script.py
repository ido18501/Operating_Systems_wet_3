#!/usr/bin/env python3
import os, sys, time, signal, socket, random, subprocess, threading, re
from collections import namedtuple, Counter
import json

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
    """Check if a port is accepting connections"""
    end_time = time.time() + timeout
    while time.time() < end_time:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(1.0)
                result = sock.connect_ex(('localhost', int(port)))
                if result == 0:
                    return True
        except Exception:
            pass
        time.sleep(0.1)
    return False


def start_server(port, pool, queue):
    print(f"{YEL}[*] Starting server on port {port} with pool={pool}, queue={queue}{RST}")
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
        return proc, False

    ready = wait_for_port(port, 3.0)
    if not ready:
        print(f"{RED}[!] Server did not bind to port {port} in time.{RST}")
        err = proc.stderr.read().decode().strip()
        if err:
            print(f"{RED}[!] Server stderr:\n{err}{RST}")
    return proc, ready


def kill_server(proc):
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGINT)
        proc.wait(timeout=2)
    except Exception:
        try:
            proc.kill()
            proc.wait(timeout=1)
        except Exception:
            pass


def run_one_client(host, port, file_, method, bucket, idx):
    try:
        cp = subprocess.run([CLIENT_BIN, host, port, file_, method],
                            capture_output=True, text=True, timeout=15)
        bucket[idx] = cp
    except subprocess.TimeoutExpired:
        bucket[idx] = None
    except Exception as e:
        bucket[idx] = None


def run_clients(reqs, port, delay=0.0):
    """Run multiple clients with optional delay between launches"""
    outs = [None] * len(reqs)
    threads = []

    def run_and_log(i, fn, m):
        if delay > 0 and i > 0:
            time.sleep(delay * i)
        run_one_client("localhost", port, fn, m, outs, i)

    for i, (fn, m) in enumerate(reqs):
        t = threading.Thread(target=run_and_log, args=(i, fn, m), daemon=True)
        threads.append(t)
        t.start()

    for t in threads:
        t.join()

    return outs


def parse_stats(output):
    """Parse all statistics from client output according to HW3 spec"""
    stats = {}
    lines = output.splitlines()

    for line in lines:
        # Request timing stats
        if "Stat-Req-Arrival::" in line:
            match = re.search(r'Stat-Req-Arrival:: ([\d.]+)', line)
            if match:
                stats['arrival'] = float(match.group(1))
        elif "Stat-Req-Dispatch::" in line:
            match = re.search(r'Stat-Req-Dispatch:: ([\d.]+)', line)
            if match:
                stats['dispatch'] = float(match.group(1))

        # Thread stats
        elif "Stat-Thread-Id::" in line:
            match = re.search(r'Stat-Thread-Id:: (\d+)', line)
            if match:
                stats['thread_id'] = int(match.group(1))
        elif "Stat-Thread-Count::" in line:
            match = re.search(r'Stat-Thread-Count:: (\d+)', line)
            if match:
                stats['thread_count'] = int(match.group(1))
        elif "Stat-Thread-Static::" in line:
            match = re.search(r'Stat-Thread-Static:: (\d+)', line)
            if match:
                stats['thread_static'] = int(match.group(1))
        elif "Stat-Thread-Dynamic::" in line:
            match = re.search(r'Stat-Thread-Dynamic:: (\d+)', line)
            if match:
                stats['thread_dynamic'] = int(match.group(1))
        elif "Stat-Thread-Post::" in line:
            match = re.search(r'Stat-Thread-Post:: (\d+)', line)
            if match:
                stats['thread_post'] = int(match.group(1))

    return stats


def find_http_status(output):
    """Find HTTP status line in client output"""
    lines = output.splitlines()

    for line in lines:
        if line.startswith("Header: HTTP/") or line.startswith("HTTP/"):
            if "200" in line:
                return "200"
            elif "404" in line:
                return "404"
            elif "403" in line:
                return "403"
            elif "501" in line:
                return "501"
            elif "400" in line or "405" in line:
                return "error"
    return None


def validate_statistics(stats, request_type, thread_pool_size):
    """Validate statistics according to HW3 requirements"""
    issues = []

    # Check required fields exist
    required_fields = ['thread_id', 'thread_count', 'thread_static', 'thread_dynamic', 'thread_post']
    for field in required_fields:
        if field not in stats:
            issues.append(f"Missing {field}")

    if issues:
        return False, issues

    # Validate thread ID range
    if not (1 <= stats['thread_id'] <= thread_pool_size):
        issues.append(f"Invalid thread_id {stats['thread_id']} (should be 1-{thread_pool_size})")

    # Validate counter logic according to spec
    total_requests = stats['thread_static'] + stats['thread_dynamic'] + stats['thread_post']
    if stats['thread_count'] < total_requests:
        issues.append(f"thread_count {stats['thread_count']} < sum of specific counters {total_requests}")

    # Validate timing stats if present
    if 'arrival' in stats and 'dispatch' in stats:
        if stats['dispatch'] < 0:
            issues.append(f"Negative dispatch time: {stats['dispatch']}")
        if stats['dispatch'] > 60:  # Very long dispatch time might indicate issues
            issues.append(f"Very long dispatch time: {stats['dispatch']}")

    return len(issues) == 0, issues


def validate_response(cp, request_type, thread_pool_size, allow_404=False):
    """Enhanced validation according to HW3 requirements"""
    if cp is None:
        return False, "Client timed out or failed"

    # Find HTTP status
    http_status = find_http_status(cp.stdout)
    if not http_status:
        return False, "No HTTP status found"

    # Check if status is acceptable
    if http_status == "200":
        pass  # Good
    elif http_status == "404" and allow_404:
        pass  # Expected for missing files
    elif http_status in ["403", "501", "error"]:
        # Error responses - acceptable for invalid methods or forbidden files
        if request_type in ["PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"]:
            return True, f"Correctly rejected invalid method with {http_status}"
    else:
        return False, f"Unexpected HTTP status: {http_status}"

    # Parse and validate statistics
    stats = parse_stats(cp.stdout)
    if not stats:
        return False, "No statistics found in response"

    stats_valid, issues = validate_statistics(stats, request_type, thread_pool_size)
    if not stats_valid:
        return False, f"Statistics validation failed: {'; '.join(issues)}"

    return True, f"Valid response (status: {http_status})"


def test_basic_functionality():
    """Test basic GET/POST functionality"""
    print(f"\n{YEL}=== Testing Basic Functionality ==={RST}")

    port = next_port()
    srv, ready = start_server(port, 2, 5)
    if not ready:
        return False

    try:
        # Test basic requests
        test_cases = [
            ("/pageA.txt", "GET", False, "Basic GET static file"),
            ("/pageB.txt", "GET", False, "Basic GET static file"),
            ("/pageC.txt", "GET", False, "Basic GET static file"),
            ("/pageA.txt", "POST", False, "Basic POST request"),
            ("/pageB.txt", "POST", False, "Basic POST request"),
            ("/missing.txt", "GET", True, "GET missing file (404)"),
            ("/missing.txt", "POST", True, "POST missing file (404)"),
            ("/pageA.txt", "PUT", False, "Invalid method PUT (should return error)"),
            ("/pageA.txt", "DELETE", False, "Invalid method DELETE (should return error)"),
        ]

        success_count = 0
        for path, method, allow_404, description in test_cases:
            print(f"{DIM}  Testing: {description}{RST}")

            reqs = [(path, method)]
            results = run_clients(reqs, port)

            if results[0]:
                valid, reason = validate_response(results[0], method, 2, allow_404)
                if valid:
                    print(f"{GREEN}  ✓ {description}: {reason}{RST}")
                    success_count += 1
                else:
                    print(f"{RED}  ✗ {description}: {reason}{RST}")
            else:
                print(f"{RED}  ✗ {description}: Client failed{RST}")

        print(f"\nBasic functionality: {success_count}/{len(test_cases)} tests passed")
        return success_count >= len(test_cases) * 0.8

    finally:
        kill_server(srv)


def test_thread_pool_functionality():
    """Test thread pool with different configurations"""
    print(f"\n{YEL}=== Testing Thread Pool Functionality ==={RST}")

    configs = [
        (1, 1, "Single thread, single queue"),
        (1, 5, "Single thread, larger queue"),
        (3, 2, "Multiple threads, small queue"),
        (5, 10, "Multiple threads, large queue"),
        (10, 5, "More threads than queue"),
    ]

    overall_success = True

    for threads, queue_size, description in configs:
        print(f"\n{DIM}Testing: {description} (threads={threads}, queue={queue_size}){RST}")

        port = next_port()
        srv, ready = start_server(port, threads, queue_size)
        if not ready:
            print(f"{RED}  ✗ Server failed to start{RST}")
            overall_success = False
            continue

        try:
            # Send multiple requests to test thread pool
            num_requests = min(15, queue_size + threads + 2)
            reqs = [("/pageA.txt", "GET")] * num_requests

            results = run_clients(reqs, port)

            success_count = 0
            thread_ids = set()

            for i, result in enumerate(results):
                if result:
                    valid, reason = validate_response(result, "GET", threads, False)
                    if valid:
                        success_count += 1
                        stats = parse_stats(result.stdout)
                        if 'thread_id' in stats:
                            thread_ids.add(stats['thread_id'])

            success_rate = success_count / len(results)
            print(f"  {success_count}/{len(results)} requests successful ({success_rate:.1%})")
            print(f"  Used {len(thread_ids)} different threads (expected max: {threads})")

            if success_rate >= 0.7 and len(thread_ids) <= threads:
                print(f"{GREEN}  ✓ {description}: PASS{RST}")
            else:
                print(f"{RED}  ✗ {description}: FAIL{RST}")
                overall_success = False

        finally:
            kill_server(srv)

    return overall_success


def test_reader_writer_synchronization():
    """Test reader-writer synchronization for GET/POST"""
    print(f"\n{YEL}=== Testing Reader-Writer Synchronization ==={RST}")

    port = next_port()
    srv, ready = start_server(port, 4, 8)
    if not ready:
        return False

    try:
        # Test 1: Multiple POSTs (readers) should work concurrently
        print(f"{DIM}  Testing concurrent POST requests (readers){RST}")
        post_reqs = [("/pageA.txt", "POST")] * 5
        post_results = run_clients(post_reqs, port)

        post_success = sum(1 for r in post_results if r and validate_response(r, "POST", 4)[0])
        print(f"  Concurrent POSTs: {post_success}/{len(post_reqs)} successful")

        # Test 2: Mix of GETs and POSTs
        print(f"{DIM}  Testing mixed GET/POST workload{RST}")
        mixed_reqs = [
            ("/pageA.txt", "GET"),
            ("/pageB.txt", "POST"),
            ("/pageC.txt", "GET"),
            ("/pageA.txt", "POST"),
            ("/pageB.txt", "GET"),
            ("/pageC.txt", "POST"),
        ]
        mixed_results = run_clients(mixed_reqs, port)

        mixed_success = 0
        for i, result in enumerate(mixed_results):
            if result:
                method = mixed_reqs[i][1]
                valid, reason = validate_response(result, method, 4)
                if valid:
                    mixed_success += 1

        print(f"  Mixed workload: {mixed_success}/{len(mixed_reqs)} successful")

        # Test 3: Verify POST returns log content (should contain previous GET entries)
        print(f"{DIM}  Testing POST log content{RST}")
        # First do some GETs to populate the log
        setup_reqs = [("/pageA.txt", "GET"), ("/pageB.txt", "GET")]
        setup_results = run_clients(setup_reqs, port)

        time.sleep(0.1)  # Brief pause

        # Now do a POST to read the log
        log_req = [("/pageA.txt", "POST")]
        log_result = run_clients(log_req, port)

        log_has_content = False
        if log_result[0] and log_result[0].stdout:
            # Check if the response body contains statistics (indicating log entries)
            if "Stat-Thread-Id::" in log_result[0].stdout or len(log_result[0].stdout) > 500:
                log_has_content = True
                print(f"{GREEN}  ✓ POST returns log content{RST}")
            else:
                print(f"{RED}  ✗ POST returned empty or minimal log{RST}")

        overall_success = (post_success >= 4 and mixed_success >= 4 and log_has_content)
        return overall_success

    finally:
        kill_server(srv)


def test_statistics_accuracy():
    """Test statistics collection and accuracy"""
    print(f"\n{YEL}=== Testing Statistics Accuracy ==={RST}")

    port = next_port()
    srv, ready = start_server(port, 3, 5)
    if not ready:
        return False

    try:
        # Sequential requests to one thread to test counter accuracy
        print(f"{DIM}  Testing sequential requests for counter accuracy{RST}")

        # Use small thread pool to increase chance of same thread handling requests
        sequential_reqs = [
            ("/pageA.txt", "GET"),  # Should increment static counter
            ("/pageB.txt", "POST"),  # Should increment post counter
            ("/pageC.txt", "GET"),  # Should increment static counter
            ("/pageA.txt", "POST"),  # Should increment post counter
        ]

        # Run with small delays to increase chance of same thread
        results = []
        for req in sequential_reqs:
            result = run_clients([req], port)
            results.append(result[0])
            time.sleep(0.1)

        # Analyze counter progression
        counter_valid = True
        prev_stats = None

        for i, result in enumerate(results):
            if not result:
                continue

            stats = parse_stats(result.stdout)
            if not stats:
                continue

            print(f"  Request {i + 1} ({sequential_reqs[i][1]} {sequential_reqs[i][0]}):")
            print(f"    Thread-Id: {stats.get('thread_id', 'N/A')}")
            print(f"    Total: {stats.get('thread_count', 'N/A')}")
            print(f"    Static: {stats.get('thread_static', 'N/A')}")
            print(f"    Dynamic: {stats.get('thread_dynamic', 'N/A')}")
            print(f"    Post: {stats.get('thread_post', 'N/A')}")

            # Validate counter logic
            if prev_stats and stats.get('thread_id') == prev_stats.get('thread_id'):
                # Same thread - counters should have progressed appropriately
                if stats.get('thread_count', 0) <= prev_stats.get('thread_count', 0):
                    print(f"{RED}    ✗ Thread count did not increase{RST}")
                    counter_valid = False

        # Test timing statistics
        print(f"\n{DIM}  Testing timing statistics{RST}")
        timing_valid = True

        for i, result in enumerate(results):
            if result:
                stats = parse_stats(result.stdout)
                if 'arrival' in stats and 'dispatch' in stats:
                    print(f"  Request {i + 1}: Arrival={stats['arrival']:.6f}, Dispatch={stats['dispatch']:.6f}")
                    if stats['dispatch'] < 0:
                        timing_valid = False
                        print(f"{RED}    ✗ Negative dispatch time{RST}")
                else:
                    print(f"{RED}  Request {i + 1}: Missing timing statistics{RST}")
                    timing_valid = False

        return counter_valid and timing_valid

    finally:
        kill_server(srv)


def test_queue_overflow():
    """Test queue overflow behavior"""
    print(f"\n{YEL}=== Testing Queue Overflow Behavior ==={RST}")

    # Test with small queue to force overflow
    port = next_port()
    srv, ready = start_server(port, 1, 2)  # 1 thread, 2 queue slots
    if not ready:
        return False

    try:
        # Send more requests than queue can handle
        print(f"{DIM}  Sending 6 requests to server with 1 thread and 2 queue slots{RST}")

        overflow_reqs = [("/pageA.txt", "GET")] * 6
        results = run_clients(overflow_reqs, port)

        success_count = sum(1 for r in results if r and validate_response(r, "GET", 1)[0])

        print(f"  {success_count}/{len(overflow_reqs)} requests completed successfully")

        # Some requests should succeed, but might not all due to queue limits
        # The key is that the server shouldn't crash
        if srv.poll() is None:  # Server still running
            print(f"{GREEN}  ✓ Server handled queue overflow gracefully{RST}")
            return True
        else:
            print(f"{RED}  ✗ Server crashed during queue overflow{RST}")
            return False

    finally:
        kill_server(srv)


def test_cgi_dynamic_content():
    """Test CGI dynamic content handling"""
    print(f"\n{YEL}=== Testing CGI Dynamic Content ==={RST}")

    # Check if CGI script exists
    cgi_path = "./public/cgi-bin/test.cgi"
    if not os.path.exists(cgi_path):
        print(f"{YEL}  Skipping CGI test - {cgi_path} not found{RST}")
        return True

    port = next_port()
    srv, ready = start_server(port, 2, 4)
    if not ready:
        return False

    try:
        # Test CGI request
        cgi_reqs = [("/cgi-bin/test.cgi", "GET")]
        results = run_clients(cgi_reqs, port)

        if results[0]:
            valid, reason = validate_response(results[0], "GET", 2)
            if valid:
                stats = parse_stats(results[0].stdout)
                # Should increment dynamic counter
                if stats.get('thread_dynamic', 0) > 0:
                    print(f"{GREEN}  ✓ CGI request handled correctly{RST}")
                    return True
                else:
                    print(f"{RED}  ✗ CGI request didn't increment dynamic counter{RST}")
                    return False
            else:
                print(f"{RED}  ✗ CGI request failed: {reason}{RST}")
                return False
        else:
            print(f"{RED}  ✗ CGI client failed{RST}")
            return False

    finally:
        kill_server(srv)


def main():
    print(f"{GREEN}HW3 Comprehensive Test Suite{RST}")
    print("=" * 50)

    # Check prerequisites
    if not os.path.exists("./public"):
        print(f"{RED}Error: ./public directory not found. Run setup script first.{RST}")
        sys.exit(1)

    required_files = ["./public/pageA.txt", "./public/pageB.txt", "./public/pageC.txt"]
    for file in required_files:
        if not os.path.exists(file):
            print(f"{RED}Error: {file} not found. Run setup script first.{RST}")
            sys.exit(1)

    # Run test suites
    test_results = {}

    test_results["Basic Functionality"] = test_basic_functionality()
    test_results["Thread Pool"] = test_thread_pool_functionality()
    test_results["Reader-Writer Sync"] = test_reader_writer_synchronization()
    test_results["Statistics Accuracy"] = test_statistics_accuracy()
    test_results["Queue Overflow"] = test_queue_overflow()
    test_results["CGI Dynamic Content"] = test_cgi_dynamic_content()

    # Summary
    print(f"\n{GREEN}=== Test Results Summary ==={RST}")
    print("=" * 50)

    passed = 0
    total = len(test_results)

    for test_name, result in test_results.items():
        status = f"{GREEN}PASS{RST}" if result else f"{RED}FAIL{RST}"
        print(f"{test_name:<25} {status}")
        if result:
            passed += 1

    print("=" * 50)
    print(f"Overall: {GREEN}{passed}{RST}/{total} test suites passed")

    if passed == total:
        print(f"\n{GREEN}🎉 All tests passed! Your implementation looks good.{RST}")
        sys.exit(0)
    else:
        print(f"\n{YEL}⚠️  Some tests failed. Check the output above for details.{RST}")
        sys.exit(1)


if __name__ == "__main__":
    main()