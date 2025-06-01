#!/bin/bash

# HW3 Test Runner Script
# Provides easy access to different testing scenarios

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

show_usage() {
    echo "HW3 Test Runner"
    echo "==============="
    echo ""
    echo "Usage: $0 <command> [options]"
    echo ""
    echo "Commands:"
    echo "  setup                    - Set up test environment"
    echo "  compile                  - Compile server and client"
    echo "  basic                    - Run basic functionality tests"
    echo "  full                     - Run comprehensive test suite"
    echo "  manual <port> <t> <q>    - Start server manually for testing"
    echo "  stress <port> <t> <q>    - Run stress test on running server"
    echo "  debug <port> <t> <q>     - Start server with debug output"
    echo "  original                 - Run original test script"
    echo "  validate                 - Validate setup and binaries"
    echo ""
    echo "Examples:"
    echo "  $0 setup                 # Set up test files"
    echo "  $0 compile               # Compile everything"
    echo "  $0 full                  # Run all tests"
    echo "  $0 manual 8080 4 10      # Start server on port 8080, 4 threads, 10 queue"
    echo "  $0 stress 8080 4 10      # Stress test server on port 8080"
    echo ""
}

check_prerequisites() {
    local missing=0
    
    echo "Checking prerequisites..."
    
    # Check for required files
    if [ ! -f "server.c" ] || [ ! -f "client.c" ]; then
        echo -e "${RED}✗ Source files (server.c, client.c) not found${NC}"
        missing=1
    else
        echo -e "${GREEN}✓ Source files found${NC}"
    fi
    
    if [ ! -f "Makefile" ]; then
        echo -e "${RED}✗ Makefile not found${NC}"
        missing=1
    else
        echo -e "${GREEN}✓ Makefile found${NC}"
    fi
    
    # Check for Python 3
    if ! command -v python3 &> /dev/null; then
        echo -e "${RED}✗ Python 3 not found${NC}"
        missing=1
    else
        echo -e "${GREEN}✓ Python 3 found${NC}"
    fi
    
    return $missing
}

setup_environment() {
    echo "Setting up test environment..."
    
    if [ ! -f "enhanced_setup_script.sh" ]; then
        echo -e "${RED}Setup script not found. Please ensure enhanced_setup_script.sh exists.${NC}"
        return 1
    fi
    
    chmod +x enhanced_setup_script.sh
    ./enhanced_setup_script.sh
    
    echo -e "${GREEN}Environment setup complete!${NC}"
}

compile_project() {
    echo "Compiling project..."
    
    if [ ! -f "Makefile" ]; then
        echo -e "${RED}Makefile not found${NC}"
        return 1
    fi
    
    make clean
    make
    
    if [ $? -eq 0 ]; then
        echo -e "${GREEN}Compilation successful!${NC}"
        return 0
    else
        echo -e "${RED}Compilation failed!${NC}"
        return 1
    fi
}

validate_setup() {
    echo "Validating setup..."
    
    local issues=0
    
    # Check binaries
    if [ ! -f "./server" ]; then
        echo -e "${RED}✗ Server binary not found${NC}"
        issues=1
    else
        echo -e "${GREEN}✓ Server binary found${NC}"
    fi
    
    if [ ! -f "./client" ]; then
        echo -e "${RED}✗ Client binary not found${NC}"
        issues=1
    else
        echo -e "${GREEN}✓ Client binary found${NC}"
    fi
    
    # Check test files
    required_files=("public/pageA.txt" "public/pageB.txt" "public/pageC.txt")
    for file in "${required_files[@]}"; do
        if [ ! -f "$file" ]; then
            echo -e "${RED}✗ Test file $file not found${NC}"
            issues=1
        else
            echo -e "${GREEN}✓ Test file $file found${NC}"
        fi
    done
    
    # Check CGI scripts
    if [ ! -f "public/cgi-bin/test.cgi" ]; then
        echo -e "${YELLOW}⚠ CGI script not found (optional)${NC}"
    else
        echo -e "${GREEN}✓ CGI script found${NC}"
    fi
    
    # Check test scripts
    if [ ! -f "comprehensive_test_script.py" ]; then
        echo -e "${RED}✗ Comprehensive test script not found${NC}"
        issues=1
    else
        echo -e "${GREEN}✓ Comprehensive test script found${NC}"
    fi
    
    if [ $issues -eq 0 ]; then
        echo -e "${GREEN}All validations passed! Ready to test.${NC}"
    else
        echo -e "${RED}Some issues found. Run 'setup' and 'compile' first.${NC}"
    fi
    
    return $issues
}

run_basic_tests() {
    echo "Running basic functionality tests..."
    
    if ! validate_setup; then
        echo -e "${RED}Setup validation failed. Cannot run tests.${NC}"
        return 1
    fi
    
    # Quick functionality test
    echo "Testing basic server startup..."
    
    PORT=$(python3 -c "import random; print(random.randint(10000, 50000))")
    
    echo "Starting server on port $PORT..."
    ./server $PORT 2 4 &
    SERVER_PID=$!
    
    sleep 2
    
    # Test if server is responding
    if kill -0 $SERVER_PID 2>/dev/null; then
        echo -e "${GREEN}✓ Server started successfully${NC}"
        
        # Try a simple request
        echo "Testing simple GET request..."
        ./client localhost $PORT /pageA.txt GET > /tmp/test_output.txt 2>&1
        
        if grep -q "HTTP" /tmp/test_output.txt; then
            echo -e "${GREEN}✓ Basic GET request successful${NC}"
        else
            echo -e "${RED}✗ Basic GET request failed${NC}"
            cat /tmp/test_output.txt
        fi
        
        # Clean up
        kill $SERVER_PID 2>/dev/null
        wait $SERVER_PID 2>/dev/null
    else
        echo -e "${RED}✗ Server failed to start${NC}"
        return 1
    fi
    
    rm -f /tmp/test_output.txt
    echo -e "${GREEN}Basic tests completed${NC}"
}

run_comprehensive_tests() {
    echo "Running comprehensive test suite..."
    
    if ! validate_setup; then
        echo -e "${RED}Setup validation failed. Cannot run tests.${NC}"
        return 1
    fi
    
    python3 comprehensive_test_script.py
}

start_manual_server() {
    local port=$1
    local threads=$2
    local queue=$3
    
    if [ -z "$port" ] || [ -z "$threads" ] || [ -z "$queue" ]; then
        echo "Usage: $0 manual <port> <threads> <queue_size>"
        return 1
    fi
    
    echo "Starting server manually..."
    echo "Port: $port, Threads: $threads, Queue: $queue"
    echo ""
    echo "Server will run in foreground. Press Ctrl+C to stop."
    echo "Test with: ./client localhost $port /pageA.txt GET"
    echo "Or browse to: http://localhost:$port/index.html"
    echo ""
    
    ./server $port $threads $queue
}

start_debug_server() {
    local port=$1
    local threads=$2
    local queue=$3
    
    if [ -z "$port" ] || [ -z "$threads" ] || [ -z "$queue" ]; then
        echo "Usage: $0 debug <port> <threads> <queue_size>"
        return 1
    fi
    
    echo "Starting server in debug mode..."
    echo "This will show server output and client interactions"
    echo ""
    
    # Start server in background
    ./server $port $threads $queue &
    SERVER_PID=$!
    
    sleep 1
    
    if kill -0 $SERVER_PID 2>/dev/null; then
        echo -e "${GREEN}Server started (PID: $SERVER_PID)${NC}"
        echo "Running some test requests..."
        echo ""
        
        # Run a few test requests
        echo "=== GET Request ==="
        ./client localhost $port /pageA.txt GET
        echo ""
        
        echo "=== POST Request ==="
        ./client localhost $port /pageB.txt POST
        echo ""
        
        echo "=== Missing File ==="
        ./client localhost $port /missing.txt GET
        echo ""
        
        echo "=== Invalid Method ==="
        ./client localhost $port /pageA.txt PUT
        echo ""
        
        echo "Debug session complete. Server still running..."
        echo "Kill with: kill $SERVER_PID"
    else
        echo -e "${RED}Server failed to start${NC}"
        return 1
    fi
}

run_stress_test() {
    local port=$1
    local threads=$2
    local queue=$3
    
    if [ -z "$port" ] || [ -z "$threads" ] || [ -z "$queue" ]; then
        echo "Usage: $0 stress <port> <threads> <queue_size>"
        return 1
    fi
    
    echo "Running stress test on server at localhost:$port"
    echo "Make sure server is already running with: ./server $port $threads $queue"
    echo ""
    
    # Test if server is responding
    if ! nc -z localhost $port 2>/dev/null; then
        echo -e "${RED}Server not responding on port $port${NC}"
        return 1
    fi
    
    echo "Server detected. Running stress test..."
    
    # Launch multiple concurrent clients
    for i in {1..20}; do
        (
            sleep $(echo "scale=2; $i * 0.1" | bc)
            ./client localhost $port /pageA.txt GET > /tmp/stress_$i.out 2>&1
        ) &
    done
    
    # Wait for all clients to complete
    wait
    
    # Analyze results
    echo "Stress test completed. Analyzing results..."
    
    success=0
    total=20
    
    for i in {1..20}; do
        if [ -f "/tmp/stress_$i.out" ] && grep -q "HTTP" /tmp/stress_$i.out; then
            ((success++))
        fi
    done
    
    echo "Results: $success/$total requests successful"
    
    if [ $success -ge $((total * 80 / 100)) ]; then
        echo -e "${GREEN}✓ Stress test passed (>80% success rate)${NC}"
    else
        echo -e "${RED}✗ Stress test failed (<80% success rate)${NC}"
    fi
    
    # Clean up
    rm -f /tmp/stress_*.out
}

run_original_tests() {
    echo "Running original test script..."
    
    if [ ! -f "paste.py" ]; then
        echo -e "${RED}Original test script (paste.py) not found${NC}"
        return 1
    fi
    
    python3 paste.py
}

# Main script logic
case "${1:-}" in
    "setup")
        setup_environment
        ;;
    "compile")
        compile_project
        ;;
    "basic")
        run_basic_tests
        ;;
    "full")
        run_comprehensive_tests
        ;;
    "manual")
        start_manual_server "$2" "$3" "$4"
        ;;
    "debug")
        start_debug_server "$2" "$3" "$4"
        ;;
    "stress")
        run_stress_test "$2" "$3" "$4"
        ;;
    "original")
        run_original_tests
        ;;
    "validate")
        validate_setup
        ;;
    "help"|"--help"|"-h")
        show_usage
        ;;
    "")
        echo -e "${YELLOW}No command specified.${NC}"
        echo ""
        show_usage
        ;;
    *)
        echo -e "${RED}Unknown command: $1${NC}"
        echo ""
        show_usage
        exit 1
        ;;
esac