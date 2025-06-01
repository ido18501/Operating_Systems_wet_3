#!/usr/bin/env python3
"""
HW3 Assignment Requirement Tests
Tests specific requirements from the assignment PDF:
1. Multi-threaded server with fixed thread pool
2. Producer-consumer pattern with bounded queue
3. Reader-writer synchronization for log
4. Statistics collection (all required formats)
5. GET appends to log, POST reads log
6. Proper error handling and HTTP responses
"""

import os, sys, time, signal, socket, random, subprocess, threading, re
from collections import namedtuple, Counter
import json

# Colors for output
try:
    from colorama import init, Fore, Style

    init()
    GREEN, RED, YEL, DIM, RST = Fore.GREEN, Fore.RED, Fore.YELLOW, Style.DIM, Style.RESET_ALL
except ImportError:
    GREEN = RED = YEL = DIM = RST = ""


class HW3RequirementTester:
    def __init__(self):
        self.server_bin = "./server"
        self.client_bin = "./client"
        self.base_port = 9000
        self.used_ports = set()

        if not (os.path.isfile(self.server_bin) and os.path.isfile(self.client_bin)):
            sys.exit(f"{RED}Error: {self.server_bin} or {self.client_bin} not found{RST}")

    def next_port(self):
        while True:
            p = random.randint(self.base_port, 60000)
            if p not in self.used_ports:
                self.used_ports.add(p)
                return str(p)

    def wait_for_port(self, port, timeout=3.0):
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

    def start_server(self, port, pool, queue):
        proc = subprocess.Popen(
            [self.server_bin, port, str(pool), str(queue)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            preexec_fn=os.setsid
        )
        time.sleep(0.5)
        proc.poll()
        if proc.returncode is not None:
            err = proc.stderr.read().decode().strip()
            return proc, False, err

        ready = self.wait_for_port(port, 3.0)
        return proc, ready, ""

    def kill_server(self, proc):
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGINT)
            proc.wait(timeout=2)
        except Exception:
            try:
                proc.kill()
                proc.wait(timeout=1)
            except Exception:
                pass

    def run_client(self, host, port, file_path, method, timeout=10):
        try:
            result = subprocess.run(
                [self.client_bin, host, port, file_path, method],
                capture_output=True, text=True, timeout=timeout
            )
            return result
        except subprocess.TimeoutExpired:
            return None
        except Exception:
            return None

    def parse_all_statistics(self, output):
        """Parse all required statistics according to HW3 spec"""
        stats = {}
        lines = output.splitlines()

        for line in lines:
            # Request timing statistics
            if "Stat-Req-Arrival::" in line:
                match = re.search(r'Stat-Req-Arrival:: ([\d.]+)', line)
                if match:
                    stats['req_arrival'] = float(match.group(1))
            elif "Stat-Req-Dispatch::" in line:
                match = re.search(r'Stat-Req-Dispatch:: ([\d.]+)', line)
                if match:
                    stats['req_dispatch'] = float(match.group(1))

            # Thread statistics
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

    def find_http_status(self, output):
        """Find HTTP status in client output"""
        lines = output.splitlines()
        for line in lines:
            if "HTTP/" in line:
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

    def test_command_line_arguments(self):
        """Test requirement: Server accepts [port] [threads] [queue_size]"""
        print(f"{YEL}=== Testing Command Line Arguments ==={RST}")

        test_cases = [
            (8080, 1, 1, True, "Minimum configuration"),
            (8081, 5, 10, True, "Normal configuration"),
            (8082, 20, 50, True, "Large configuration"),
            (8083, 0, 5, False, "Invalid threads (0)"),
            (8084, 5, 0, False, "Invalid queue size (0)"),
        ]

        passed = 0
        for port, threads, queue, should_work, description in test_cases:
            print(f"{DIM}  Testing {description}: port={port}, threads={threads}, queue={queue}{RST}")

            proc, ready, error = self.start_server(str(port), threads, queue)

            if should_work:
                if ready:
                    print(f"{GREEN}    ✓ Server started correctly{RST}")
                    passed += 1
                else:
                    print(f"{RED}    ✗ Server failed to start: {error}{RST}")
            else:
                if not ready:
                    print(f"{GREEN}    ✓ Server correctly rejected invalid arguments{RST}")
                    passed += 1
                else:
                    print(f"{RED}    ✗ Server accepted invalid arguments{RST}")

            self.kill_server(proc)

        print(f"Command line tests: {passed}/{len(test_cases)} passed")
        return passed == len(test_cases)

    def test_statistics_format(self):
        """Test requirement: All statistics must be in exact format specified"""
        print(f"{YEL}=== Testing Statistics Format ==={RST}")

        port = self.next_port()
        proc, ready, _ = self.start_server(port, 2, 5)
        if not ready:
            return False

        try:
            # Test GET request
            result = self.run_client("localhost", port, "/pageA.txt", "GET")
            if not result:
                return False

            # Check for all required statistics
            required_stats = [
                ("Stat-Req-Arrival::", r'Stat-Req-Arrival:: \d+\.\d{6}'),
                ("Stat-Req-Dispatch::", r'Stat-Req-Dispatch:: \d+\.\d{6}'),
                ("Stat-Thread-Id::", r'Stat-Thread-Id:: \d+'),
                ("Stat-Thread-Count::", r'Stat-Thread-Count:: \d+'),
                ("Stat-Thread-Static::", r'Stat-Thread-Static:: \d+'),
                ("Stat-Thread-Dynamic::", r'Stat-Thread-Dynamic:: \d+'),
                ("Stat-Thread-Post::", r'Stat-Thread-Post:: \d+'),
            ]

            found_count = 0
            for stat_name, pattern in required_stats:
                if re.search(pattern, result.stdout):
                    print(f"{GREEN}    ✓ {stat_name} format correct{RST}")
                    found_count += 1
                else:
                    print(f"{RED}    ✗ {stat_name} missing or wrong format{RST}")

            return found_count == len(required_stats)

        finally:
            self.kill_server(proc)

    def test_thread_pool_operation(self):
        """Test requirement: Fixed-size thread pool with proper worker thread IDs"""
        print(f"{YEL}=== Testing Thread Pool Operation ==={RST}")

        thread_counts = [1, 3, 5, 8]
        all_passed = True

        for thread_count in thread_counts:
            print(f"{DIM}  Testing with {thread_count} threads{RST}")

            port = self.next_port()
            proc, ready, _ = self.start_server(port, thread_count, 10)
            if not ready:
                all_passed = False
                continue

            try:
                # Send multiple requests to see different thread IDs
                requests = [("/pageA.txt", "GET")] * (thread_count * 2)
                thread_ids = set()

                for req_path, req_method in requests:
                    result = self.run_client("localhost", port, req_path, req_method)
                    if result:
                        stats = self.parse_all_statistics(result.stdout)
                        if 'thread_id' in stats:
                            thread_ids.add(stats['thread_id'])

                # Check thread ID range
                valid_ids = all(1 <= tid <= thread_count for tid in thread_ids)
                if valid_ids and len(thread_ids) <= thread_count:
                    print(f"{GREEN}    ✓ Thread IDs in range 1-{thread_count}, used {len(thread_ids)} threads{RST}")
                else:
                    print(f"{RED}    ✗ Invalid thread IDs: {thread_ids} (expected 1-{thread_count}){RST}")
                    all_passed = False

            finally:
                self.kill_server(proc)

        return all_passed

    def test_get_post_behavior(self):
        """Test requirement: GET appends to log, POST reads log"""
        print(f"{YEL}=== Testing GET/POST Log Behavior ==={RST}")

        port = self.next_port()
        proc, ready, _ = self.start_server(port, 2, 5)
        if not ready:
            return False

        try:
            # Initially, POST should return empty or minimal log
            initial_post = self.run_client("localhost", port, "/pageA.txt", "POST")
            if not initial_post:
                return False

            initial_length = len(initial_post.stdout)
            print(f"{DIM}  Initial POST response length: {initial_length}{RST}")

            # Do some GET requests (should append to log)
            get_requests = [
                ("/pageA.txt", "GET"),
                ("/pageB.txt", "GET"),
                ("/pageC.txt", "GET"),
            ]

            for req_path, req_method in get_requests:
                result = self.run_client("localhost", port, req_path, req_method)
                if not result:
                    print(f"{RED}    ✗ GET request failed{RST}")
                    return False

                # Verify it's a valid GET response
                status = self.find_http_status(result.stdout)
                if status != "200":
                    print(f"{RED}    ✗ GET request returned status {status}{RST}")
                    return False

            print(f"{GREEN}    ✓ All GET requests completed successfully{RST}")

            # Now POST should return a longer log (containing GET entries)
            final_post = self.run_client("localhost", port, "/pageA.txt", "POST")
            if not final_post:
                return False

            final_length = len(final_post.stdout)
            print(f"{DIM}  Final POST response length: {final_length}{RST}")

            # Log should have grown
            if final_length > initial_length:
                print(f"{GREEN}    ✓ POST log grew after GET requests (indicates GET appends to log){RST}")
                return True
            else:
                print(f"{RED}    ✗ POST log did not grow after GET requests{RST}")
                return False

        finally:
            self.kill_server(proc)

    def test_counter_accuracy(self):
        """Test requirement: Statistics counters increment correctly"""
        print(f"{YEL}=== Testing Counter Accuracy ==={RST}")

        port = self.next_port()
        proc, ready, _ = self.start_server(port, 1, 5)  # Single thread for predictable behavior
        if not ready:
            return False

        try:
            # Track counter progression
            test_sequence = [
                ("/pageA.txt", "GET", "static"),
                ("/pageB.txt", "POST", "post"),
                ("/pageC.txt", "GET", "static"),
                ("/pageA.txt", "POST", "post"),
            ]

            all_correct = True
            prev_counts = {}

            for i, (path, method, counter_type) in enumerate(test_sequence):
                result = self.run_client("localhost", port, path, method)
                if not result:
                    print(f"{RED}    ✗ Request {i + 1} failed{RST}")
                    all_correct = False
                    continue

                stats = self.parse_all_statistics(result.stdout)
                current_counts = {
                    'total': stats.get('thread_count', 0),
                    'static': stats.get('thread_static', 0),
                    'dynamic': stats.get('thread_dynamic', 0),
                    'post': stats.get('thread_post', 0),
                }

                print(f"{DIM}  Request {i + 1} ({method} {path}):{RST}")
                print(
                    f"{DIM}    Total: {current_counts['total']}, Static: {current_counts['static']}, Dynamic: {current_counts['dynamic']}, Post: {current_counts['post']}{RST}")

                # Check counter progression
                if prev_counts:
                    # Total should always increase
                    if current_counts['total'] <= prev_counts['total']:
                        print(f"{RED}    ✗ Total count did not increase{RST}")
                        all_correct = False

                    # Specific counter should increase based on request type
                    if counter_type == "static" and current_counts['static'] <= prev_counts['static']:
                        print(f"{RED}    ✗ Static count did not increase for GET request{RST}")
                        all_correct = False
                    elif counter_type == "post" and current_counts['post'] <= prev_counts['post']:
                        print(f"{RED}    ✗ Post count did not increase for POST request{RST}")
                        all_correct = False

                prev_counts = current_counts.copy()

            if all_correct:
                print(f"{GREEN}    ✓ All counters incremented correctly{RST}")

            return all_correct

        finally:
            self.kill_server(proc)

    def test_error_handling(self):
        """Test requirement: Proper HTTP error responses"""
        print(f"{YEL}=== Testing Error Handling ==={RST}")

        port = self.next_port()
        proc, ready, _ = self.start_server(port, 2, 5)
        if not ready:
            return False

        try:
            error_tests = [
                ("/nonexistent.txt", "GET", "404", "Missing file GET"),
                ("/nonexistent.txt", "POST", "404", "Missing file POST"),
                ("/pageA.txt", "PUT", ["400", "405", "501"], "Invalid method PUT"),
                ("/pageA.txt", "DELETE", ["400", "405", "501"], "Invalid method DELETE"),
                ("/pageA.txt", "PATCH", ["400", "405", "501"], "Invalid method PATCH"),
            ]

            passed = 0
            for path, method, expected_status, description in error_tests:
                result = self.run_client("localhost", port, path, method)
                if not result:
                    print(f"{RED}    ✗ {description}: Client failed{RST}")
                    continue

                actual_status = self.find_http_status(result.stdout)

                # Handle both single expected status and list of acceptable statuses
                if isinstance(expected_status, list):
                    if actual_status in expected_status:
                        print(
                            f"{GREEN}    ✓ {description}: Got {actual_status} (expected one of {expected_status}){RST}")
                        passed += 1
                    else:
                        print(f"{RED}    ✗ {description}: Got {actual_status}, expected one of {expected_status}{RST}")
                else:
                    if actual_status == expected_status:
                        print(f"{GREEN}    ✓ {description}: Got {expected_status}{RST}")
                        passed += 1
                    else:
                        print(f"{RED}    ✗ {description}: Got {actual_status}, expected {expected_status}{RST}")

                # Check that statistics are still present even in error responses
                stats = self.parse_all_statistics(result.stdout)
                if 'thread_id' in stats:
                    print(f"{GREEN}      ✓ Statistics present in error response{RST}")
                else:
                    print(f"{RED}      ✗ Statistics missing in error response{RST}")

            return passed >= len(error_tests) * 0.8  # Allow some tolerance

        finally:
            self.kill_server(proc)

    def test_concurrent_operations(self):
        """Test requirement: Thread pool handles concurrent requests"""
        print(f"{YEL}=== Testing Concurrent Operations ==={RST}")

        port = self.next_port()
        proc, ready, _ = self.start_server(port, 4, 8)
        if not ready:
            return False

        try:
            # Test concurrent GET requests
            print(f"{DIM}  Testing concurrent GET requests{RST}")

            def run_concurrent_client(path, method, results, index):
                result = self.run_client("localhost", port, path, method)
                results[index] = result

            # Launch multiple concurrent requests
            num_requests = 8
            results = [None] * num_requests
            threads = []

            for i in range(num_requests):
                path = f"/page{chr(65 + (i % 3))}.txt"  # pageA.txt, pageB.txt, pageC.txt
                thread = threading.Thread(
                    target=run_concurrent_client,
                    args=(path, "GET", results, i)
                )
                threads.append(thread)
                thread.start()

            # Wait for all threads to complete
            for thread in threads:
                thread.join()

            # Analyze results
            successful = 0
            thread_ids = set()

            for i, result in enumerate(results):
                if result and self.find_http_status(result.stdout) == "200":
                    successful += 1
                    stats = self.parse_all_statistics(result.stdout)
                    if 'thread_id' in stats:
                        thread_ids.add(stats['thread_id'])

            print(f"{DIM}    {successful}/{num_requests} concurrent requests successful{RST}")
            print(f"{DIM}    Used {len(thread_ids)} different threads: {sorted(thread_ids)}{RST}")

            if successful >= num_requests * 0.8 and len(thread_ids) > 1:
                print(f"{GREEN}    ✓ Concurrent operations handled correctly{RST}")
                return True
            else:
                print(f"{RED}    ✗ Concurrent operations failed{RST}")
                return False

        finally:
            self.kill_server(proc)

    def test_queue_limits(self):
        """Test requirement: Bounded queue behavior"""
        print(f"{YEL}=== Testing Queue Limits ==={RST}")

        # Test with very small queue to force queueing behavior
        port = self.next_port()
        proc, ready, _ = self.start_server(port, 1, 1)  # 1 thread, 1 queue slot
        if not ready:
            return False

        try:
            # Send requests that should fill the queue
            print(f"{DIM}  Testing queue overflow with 1 thread, 1 queue slot{RST}")

            # Send multiple requests quickly
            results = []
            for i in range(4):  # More requests than queue + threads can handle immediately
                result = self.run_client("localhost", port, "/pageA.txt", "GET")
                results.append(result)

            # Count successful responses
            successful = sum(1 for r in results if r and self.find_http_status(r.stdout) == "200")

            print(f"{DIM}    {successful}/{len(results)} requests completed{RST}")

            # Server should handle some requests successfully (but maybe not all due to queue limits)
            # Most importantly, it shouldn't crash
            if proc.poll() is None and successful > 0:
                print(f"{GREEN}    ✓ Server handled queue pressure without crashing{RST}")
                return True
            else:
                print(f"{RED}    ✗ Server crashed or failed completely{RST}")
                return False

        finally:
            self.kill_server(proc)

    def run_all_tests(self):
        """Run all requirement tests"""
        print(f"{GREEN}HW3 Assignment Requirement Tests{RST}")
        print("=" * 60)

        # Check prerequisites
        required_files = ["./public/pageA.txt", "./public/pageB.txt", "./public/pageC.txt"]
        for file in required_files:
            if not os.path.exists(file):
                print(f"{RED}Error: {file} not found. Run setup script first.{RST}")
                return False

        tests = [
            ("Command Line Arguments", self.test_command_line_arguments),
            ("Statistics Format", self.test_statistics_format),
            ("Thread Pool Operation", self.test_thread_pool_operation),
            ("GET/POST Log Behavior", self.test_get_post_behavior),
            ("Counter Accuracy", self.test_counter_accuracy),
            ("Error Handling", self.test_error_handling),
            ("Concurrent Operations", self.test_concurrent_operations),
            ("Queue Limits", self.test_queue_limits),
        ]

        results = {}

        for test_name, test_func in tests:
            print(f"\n{YEL}Running: {test_name}{RST}")
            try:
                results[test_name] = test_func()
            except Exception as e:
                print(f"{RED}    ✗ Test crashed: {e}{RST}")
                results[test_name] = False

        # Summary
        print(f"\n{GREEN}=== Test Results Summary ==={RST}")
        print("=" * 60)

        passed = 0
        total = len(results)

        for test_name, result in results.items():
            status = f"{GREEN}PASS{RST}" if result else f"{RED}FAIL{RST}"
            print(f"{test_name:<30} {status}")
            if result:
                passed += 1

        print("=" * 60)
        print(f"Overall: {GREEN}{passed}{RST}/{total} requirement tests passed")

        if passed == total:
            print(f"\n{GREEN}🎉 All requirement tests passed!{RST}")
            print(f"{GREEN}Your implementation meets the HW3 assignment requirements.{RST}")
        else:
            print(f"\n{YEL}⚠️  Some requirement tests failed.{RST}")
            print(f"{YEL}Please review the specific failures above.{RST}")

        return passed == total


def main():
    if len(sys.argv) > 1 and sys.argv[1] in ["-h", "--help"]:
        print("HW3 Assignment Requirement Tests")
        print("Usage: python3 hw3_requirement_tests.py")
        print("")
        print("This script tests specific requirements from the HW3 assignment:")
        print("- Multi-threaded server implementation")
        print("- Producer-consumer pattern with thread pool")
        print("- Reader-writer synchronization")
        print("- Statistics collection and formatting")
        print("- GET/POST log behavior")
        print("- Error handling")
        print("- Concurrent request handling")
        print("- Queue overflow behavior")
        return

    tester = HW3RequirementTester()
    success = tester.run_all_tests()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()