"""Three real processes: simulator -> Python gateway -> TLS relay -> user API."""
import json
import os
import socket
import ssl
import subprocess
import sys
import time
import httpx
from plc_access.security import hash_password


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def test_full_path(tmp_path):
    cert, key = tmp_path/'cert.pem', tmp_path/'key.pem'
    subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','1',
                    '-keyout',str(key),'-out',str(cert),'-subj','/CN=localhost',
                    '-addext','subjectAltName=DNS:localhost'], check=True, capture_output=True)
    users, token = tmp_path/'users.json', tmp_path/'token'
    password = 'integration-test-password'
    users.write_text(json.dumps({'operator': {'role':'operator','password_hash':hash_password(password)}}))
    token.write_text('integration-token-' * 4)
    relay_port, plc_port = free_port(), free_port()
    env = {**os.environ, 'USERS_FILE':str(users), 'GATEWAY_TOKEN_FILE':str(token),
           'RELAY_ALLOW_WRITES':'true', 'GATEWAY_READ_ONLY':'false',
           'RELAY_URL':f'https://localhost:{relay_port}', 'RELAY_CA_FILE':str(cert),
           'PLC_HOST':'127.0.0.1','PLC_PORT':str(plc_port), 'SIM_PORT':str(plc_port), 'SIM_HOST':'127.0.0.1'}
    processes = []
    def start(*args):
        p = subprocess.Popen([sys.executable, *args], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        processes.append(p)
        return p
    try:
        start('-m','plc_access.simulator')
        start('-m','uvicorn','plc_access.relay:from_env','--factory','--host','127.0.0.1',
              '--port',str(relay_port),'--ssl-keyfile',str(key),'--ssl-certfile',str(cert),'--no-access-log')
        start('-m','plc_access.gateway')
        with httpx.Client(base_url=env['RELAY_URL'], verify=ssl.create_default_context(cafile=str(cert)),
                          auth=('operator',password), trust_env=False, timeout=1) as client:
            def wait_for(predicate):
                for _ in range(120):
                    assert all(p.poll() is None for p in processes), 'Service exited early'
                    try:
                        status = client.get('/api/status').json()
                        if predicate(status):
                            return status
                    except (httpx.HTTPError, ValueError):
                        pass
                    time.sleep(0.1)
                raise AssertionError('Timed out waiting for end-to-end result')
            assert wait_for(lambda s:s['fresh'])['sample']['values']['setpoint_c'] == 25
            response = client.post('/api/setpoint', json={'value':28}, headers={'X-PLC-Action':'setpoint'})
            assert response.status_code == 202
            status = wait_for(lambda s:s['command'] and s['command']['status'] == 'applied')
            assert status['sample']['values']['setpoint_c'] == 28
    finally:
        for p in reversed(processes):
            p.terminate()
        for p in processes:
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait()
