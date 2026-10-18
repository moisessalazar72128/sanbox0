"""Fixed Modbus map, zero-based PDU addresses, device ID configured locally only."""
from pymodbus.client import AsyncModbusTcpClient


class ModbusAdapter:
    def __init__(self, host: str, port=5020, device_id=1, read_only=True):
        self.client = AsyncModbusTcpClient(host, port=port, timeout=2, retries=0)
        self.device_id = device_id
        self.read_only = read_only

    async def connect(self):
        if not self.client.connected and not await self.client.connect():
            raise ConnectionError("PLC unavailable")

    async def read(self):
        await self.connect()
        response = await self.client.read_holding_registers(0, count=3, device_id=self.device_id)
        if response.isError() or len(response.registers) != 3:
            raise IOError("PLC read failed")
        temp, running, setpoint = response.registers
        return {"temperature_c": temp / 10, "running": bool(running), "setpoint_c": setpoint / 10}

    async def write_setpoint(self, value: int):
        if self.read_only:
            raise PermissionError("Gateway read-only policy")
        if type(value) is not int or not 15 <= value <= 35:
            raise ValueError("Setpoint must be an integer between 15 and 35 C")
        await self.connect()
        response = await self.client.write_register(2, value * 10, device_id=self.device_id)
        if response.isError():
            raise IOError("PLC write failed")

    def close(self):
        self.client.close()
