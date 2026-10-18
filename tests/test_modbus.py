import socket
import pytest
from pymodbus.server import ModbusTcpServer
from plc_access.adapter import ModbusAdapter
from plc_access.gateway import execute, validate_url
from plc_access.simulator import make_context
@pytest.mark.parametrize('url', ['http://example.com', 'https://u:p@example.com', 'https://example.com/path', 'https://example.com?token=x'])
def test_https_required(url):
    with pytest.raises(ValueError):
        validate_url(url)
@pytest.mark.asyncio
async def test_real_modbus_wire_and_policy():
    _, context = make_context()
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    server = ModbusTcpServer(context, address=('127.0.0.1', port))
    await server.serve_forever(background=True)
    ro = ModbusAdapter('127.0.0.1', port)
    rw = ModbusAdapter('127.0.0.1', port, read_only=False)
    try:
        assert await ro.read() == {'temperature_c':24.0, 'running':True, 'setpoint_c':25.0}
        with pytest.raises(PermissionError):
            await ro.write_setpoint(26)
        assert (await execute(ro, {'id':'one', 'value':26, 'expires_at':1005}, clock=lambda:1000))['status'] == 'rejected'
        assert (await execute(rw, {'id':'two', 'value':26, 'expires_at':999}, clock=lambda:1000))['status'] == 'rejected'
        assert (await execute(rw, {'id':'three', 'value':100, 'expires_at':1005}, clock=lambda:1000))['status'] == 'rejected'
        assert (await execute(rw, {'id':'four', 'value':26, 'expires_at':1005}, clock=lambda:1000))['status'] == 'applied'
        assert (await ro.read())['setpoint_c'] == 26
    finally:
        ro.close()
        rw.close()
        await server.shutdown()
