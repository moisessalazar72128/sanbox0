"""Modbus simulator, holding registers 0=temperature*10, 1=running, 2=setpoint*10."""
import asyncio
import math
import os
from pymodbus.datastore import ModbusDeviceContext, ModbusSequentialDataBlock, ModbusServerContext
from pymodbus.server import StartAsyncTcpServer


def make_context():
    # DeviceContext offsets PDU address by one internally.
    device = ModbusDeviceContext(hr=ModbusSequentialDataBlock(1, [240, 1, 250] + [0] * 13))
    return device, ModbusServerContext(devices={1: device}, single=False)


async def run():
    device, context = make_context()

    async def update():
        tick = 0
        while True:
            device.setValues(3, 0, [int(240 + 15 * math.sin(tick / 10)), 1])
            tick += 1
            await asyncio.sleep(1)

    task = asyncio.create_task(update())
    try:
        await StartAsyncTcpServer(context=context, address=(os.getenv("SIM_HOST", "0.0.0.0"), int(os.getenv("SIM_PORT", "5020"))))
    finally:
        task.cancel()


if __name__ == "__main__":
    asyncio.run(run())
