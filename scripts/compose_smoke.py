"""CI-only smoke test. Refuses existing secrets; starts/stops an isolated Compose lab."""
import json
from pathlib import Path
import secrets
import shutil
import ssl
import subprocess
import sys
import time
import httpx
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from plc_access.security import hash_password


def docker(*args, **kwargs):
    return subprocess.run(['docker', 'compose', *args], check=True, **kwargs)


def main():
    if Path('secrets').exists() or Path('.env').exists():
        raise SystemExit('Smoke test requires a clean CI checkout without secrets/ or .env')
    password = secrets.token_urlsafe(24)
    Path('secrets').mkdir(mode=0o700)
    Path('secrets/users.json').write_text(json.dumps({'viewer': {'role':'viewer','password_hash':hash_password(password)}}))
    Path('secrets/gateway_token').write_text(secrets.token_urlsafe(48))
    try:
        docker('up', '-d', '--build')
        ca = Path('secrets/local-ca.crt')
        for _ in range(60):
            result = subprocess.run(['docker','compose','cp','proxy:/data/caddy/pki/authorities/local/root.crt',str(ca)], capture_output=True)
            if result.returncode == 0:
                break
            time.sleep(1)
        context = ssl.create_default_context(cafile=str(ca))
        with httpx.Client(verify=context, auth=('viewer',password), trust_env=False) as client:
            for _ in range(60):
                try:
                    response = client.get('https://localhost:8443/api/status')
                    response.raise_for_status()
                    if response.json()['fresh']:
                        print('Compose smoke test passed: authenticated HTTPS telemetry from simulator.')
                        return
                except (httpx.HTTPError, ValueError):
                    pass
                time.sleep(1)
        raise RuntimeError('No fresh telemetry from Compose stack')
    finally:
        docker('logs', '--tail=30', 'gateway', 'relay')
        docker('down', '-v')
        shutil.rmtree('secrets')


if __name__ == '__main__':
    main()
