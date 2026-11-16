#!/usr/bin/env python3
"""
Local HTTP server for the NIST Group Demo VRML viewer.
Run this from the grpDemo folder, then open http://localhost:8080/index.html

Usage:
    python3 serve.py
    python3 serve.py 8086   # custom port
"""
import http.server, socketserver, sys, os, webbrowser, threading, time

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8086

# Make sure we serve from our own directory
os.chdir(os.path.dirname(os.path.abspath(__file__)))

class Handler(http.server.SimpleHTTPRequestHandler):
    # Add CORS headers so Three.js can load sub-files
    def end_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Cache-Control', 'no-cache')
        super().end_headers()

    # Serve .wrl files as text/plain so browsers don't try to download them
    extensions_map = {
        **http.server.SimpleHTTPRequestHandler.extensions_map,
        '.wrl':  'model/vrml',
        '.wav':  'audio/wav',
        '.au':   'audio/basic',
        '.mpg':  'video/mpeg',
    }

    def log_message(self, format, *args):
        # Quieter logging
        if args[1] not in ('200', '304'):
            super().log_message(format, *args)

def open_browser():
    time.sleep(0.8)
    webbrowser.open(f'http://localhost:{PORT}/xite.html')

print(f'\n  NIST Group Demo viewer')
print(f'  Serving on http://localhost:{PORT}/xite.html  (X_ITE player)')
print(f'  Press Ctrl+C to stop\n')

threading.Thread(target=open_browser, daemon=True).start()

with socketserver.TCPServer(('', PORT), Handler) as httpd:
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print('\nServer stopped.')
