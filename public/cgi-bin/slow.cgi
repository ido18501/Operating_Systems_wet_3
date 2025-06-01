#!/bin/bash
echo "Content-Type: text/html"
echo ""
echo "<html><head><title>Slow CGI Test</title></head><body>"
echo "<h1>Slow CGI Script</h1>"
echo "<p>This script sleeps for 2 seconds to test concurrent handling...</p>"
sleep 2
echo "<p>Done sleeping! Current time: $(date)</p>"
echo "</body></html>"
