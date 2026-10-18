import pytest
from fastapi.testclient import TestClient
from plc_access.relay import create_app
from plc_access.security import hash_password, verify_password
TOKEN = 'test-token-' * 6
PASSWORD = 'long-test-password'
HEADERS = {'X-PLC-Action': 'setpoint'}
SAMPLE = {'quality': 'good', 'values': {'temperature_c': 24.0, 'running': True, 'setpoint_c': 25.0}, 'writable': True}
@pytest.fixture
def setup():
    now = [1000.0]
    users = {name: {'role': name, 'password_hash': hash_password(PASSWORD)} for name in ['viewer', 'operator']}
    return lambda writes=False: TestClient(create_app(users, TOKEN, writes, clock=lambda: now[0])), now

def feed(c, sample=None):
    return c.post('/api/gateway/exchange', headers={'Authorization': f'Bearer {TOKEN}'}, json=sample or SAMPLE)
def write(c, role='operator', value=26, headers=HEADERS):
    return c.post('/api/setpoint', auth=(role, PASSWORD), headers=headers, json={'value': value})
def test_password():
    hashed = hash_password(PASSWORD)
    assert verify_password(PASSWORD, hashed)
    assert not verify_password('wrong', hashed)
    assert not verify_password(PASSWORD, 'broken')
def test_auth_boundaries(setup):
    build, _ = setup
    c = build()
    for path in ['/', '/api/status', '/app.js', '/style.css']:
        assert c.get(path).status_code == 401
    assert c.get('/api/status', auth=('viewer', 'wrong')).status_code == 401
    assert c.post('/api/gateway/exchange', json=SAMPLE).status_code == 401
    assert c.post('/api/gateway/exchange', auth=('operator', PASSWORD), json=SAMPLE).status_code == 401
    assert c.get('/api/status', headers={'Authorization': f'Bearer {TOKEN}'}).status_code == 401
    assert c.get('/', auth=('viewer', PASSWORD)).status_code == 200

def test_read_only_role_and_csrf(setup):
    build, _ = setup
    c = build()
    feed(c)
    assert write(c).status_code == 403
    c = build(True)
    feed(c)
    assert write(c, role='viewer').status_code == 403
    assert write(c, headers={}).status_code == 403
    assert c.options('/api/setpoint', headers={'Origin':'https://evil.example', 'Access-Control-Request-Method':'POST', 'Access-Control-Request-Headers':'X-PLC-Action'}).status_code == 405
    feed(c, {**SAMPLE, 'writable': False})
    assert write(c).status_code == 409

def test_delivery_expiry_and_freshness(setup):
    build, now = setup
    c = build(True)
    assert write(c).status_code == 409
    assert feed(c).status_code == 200
    queued = write(c).json()
    assert write(c).status_code == 409
    assert feed(c).json()['command']['id'] == queued['id']
    assert feed(c).json()['command'] is None
    assert write(c).status_code == 409
    feed(c, {**SAMPLE, 'result': {'id': queued['id'], 'status':'applied'}})
    assert c.get('/api/status', auth=('viewer', PASSWORD)).json()['command']['status'] == 'applied'
    assert write(c).status_code == 202
    now[0] += 6
    assert feed(c).json()['command'] is None
    assert c.get('/api/status', auth=('viewer', PASSWORD)).json()['command']['status'] == 'expired'
    now[0] += 11
    assert not c.get('/api/status', auth=('viewer', PASSWORD)).json()['fresh']
    assert write(c).status_code == 409

@pytest.mark.parametrize('value', [14, 36, 25.5, '25', True])
def test_reject_invalid_setpoint(setup, value):
    build, _ = setup
    c = build(True)
    feed(c)
    assert write(c, value=value).status_code == 422

def test_quality_and_schema(setup):
    build, _ = setup
    c = build()
    assert feed(c, {**SAMPLE, 'quality': 'unavailable'}).status_code == 422
    assert feed(c, {**SAMPLE, 'address': 200}).status_code == 422
    assert feed(c, {'quality':'unavailable'}).status_code == 200
    status = c.get('/api/status', auth=('viewer', PASSWORD))
    assert not status.json()['fresh']
    assert status.headers['cache-control'] == 'no-store'
    assert 'frame-ancestors' in status.headers['content-security-policy']

def test_rate_limit(setup):
    build, _ = setup
    c = build()
    for _ in range(20):
        assert c.get('/api/status', auth=('unknown', 'bad')).status_code == 401
    assert c.get('/api/status', auth=('viewer', PASSWORD)).status_code == 429
