#!/bin/bash
echo "Content-Type: text/html"
echo ""
echo "<html><head><title>CGI Parameters Test</title></head><body>"
echo "<h1>CGI Parameters Test</h1>"
echo "<p>Query String: $QUERY_STRING</p>"
echo "<p>This tests parameter passing to CGI scripts.</p>"
echo "</body></html>"
