import ssl
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
import httpx
import pytest

def test_tls_certificate_validation(tmp_path):
    key, cert = tmp_path/'key.pem', tmp_path/'cert.pem'
    subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','1','-keyout',str(key),'-out',str(cert),'-subj','/CN=localhost','-addext','subjectAltName=DNS:localhost'], check=True, capture_output=True)
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'ok')
        def log_message(self, *args):
            pass
    server = HTTPServer(('127.0.0.1',0), Handler)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(cert, key)
    server.socket = ctx.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f'https://localhost:{server.server_port}'
    try:
        with httpx.Client(trust_env=False) as client:
            with pytest.raises(httpx.ConnectError):
                client.get(url)
        with httpx.Client(verify=ssl.create_default_context(cafile=str(cert)), trust_env=False) as client:
            assert client.get(url).text == 'ok'
            with pytest.raises(httpx.ConnectError):
                client.get(url.replace('localhost', '127.0.0.1'))
    finally:
        server.shutdown()
        thread.join(timeout=3)
        server.server_close()
