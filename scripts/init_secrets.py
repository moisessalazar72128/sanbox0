"""Run from repository root. Refuses to overwrite an existing installation."""
import getpass
import json
import os
from pathlib import Path
import secrets
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from plc_access.security import hash_password


def main():
    root = Path('secrets')
    if root.exists() or Path('.env').exists():
        raise SystemExit('secrets/ or .env already exists. Back up and rotate deliberately; nothing overwritten.')
    users = {}
    for name, role in [('viewer', 'viewer'), ('operator', 'operator')]:
        password = getpass.getpass(f'{name} password (at least 14 characters): ')
        if len(password) < 14:
            raise SystemExit('Password too short; nothing written.')
        users[name] = {'role': role, 'password_hash': hash_password(password)}
    root.mkdir(mode=0o700)
    for name, content in [('users.json', json.dumps(users, indent=2)), ('gateway_token', secrets.token_urlsafe(48))]:
        path = root / name
        path.touch(mode=0o600)
        path.write_text(content + '\n')
    env = Path('.env')
    env.touch(mode=0o600)
    env.write_text(f'LOCAL_UID={getattr(os, "getuid", lambda: 1000)()}\nLOCAL_GID={getattr(os, "getgid", lambda: 1000)()}\nRELAY_ALLOW_WRITES=false\nGATEWAY_READ_ONLY=true\n')
    print('Created local configuration. Passwords and gateway token are not printed.')


if __name__ == '__main__':
    main()
