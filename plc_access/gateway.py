"""Outbound HTTPS telemetry/command polling, never a listening server."""
import asyncio
import logging
import os
import ssl
import time
from pathlib import Path
from urllib.parse import urlparse
import httpx
from .adapter import ModbusAdapter
from .models import Setpoint

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s %(message)s')
log = logging.getLogger("gateway")


def validate_url(url):
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ("", "/"):
        raise ValueError("RELAY_URL must be an HTTPS origin without credentials or path")
    return url.rstrip("/")


async def execute(adapter, command, clock=time.time):
    result = {"id": str(command.get("id", ""))[:36], "status": "rejected"}
    try:
        if not isinstance(command.get("expires_at"), (int, float)) or not clock() < command["expires_at"] <= clock() + 10:
            return result
        body = Setpoint(value=command["value"])
        await adapter.write_setpoint(body.value)
        result["status"] = "applied"
    except (PermissionError, ValueError, KeyError):
        pass
    except Exception:
        result["status"] = "failed_or_unknown"
    log.info("event=command_result id=%s status=%s", result["id"], result["status"])
    return result


async def run():
    url = validate_url(os.environ["RELAY_URL"])
    token = Path(os.environ["GATEWAY_TOKEN_FILE"]).read_text().strip()
    if len(token) < 32:
        raise ValueError("Gateway token too short")
    ca = os.getenv("RELAY_CA_FILE")
    # Local Caddy may still be provisioning its CA. No insecure fallback.
    while ca and not Path(ca).is_file():
        log.info("event=waiting_for_local_ca")
        await asyncio.sleep(2)
    context = ssl.create_default_context(cafile=ca)
    adapter = ModbusAdapter(os.getenv("PLC_HOST", "simulator"), int(os.getenv("PLC_PORT", "5020")),
                            int(os.getenv("PLC_DEVICE_ID", "1")),
                            os.getenv("GATEWAY_READ_ONLY", "true").lower() != "false")
    result = None
    async with httpx.AsyncClient(verify=context, timeout=5, trust_env=False, follow_redirects=False) as client:
        try:
            while True:
                values = None
                try:
                    values = await adapter.read()
                except Exception:
                    adapter.close()
                    log.warning("event=plc_unavailable")
                payload = {"values": values, "quality": "good" if values else "unavailable",
                           "writable": not adapter.read_only, "result": result}
                try:
                    response = await client.post(url + "/api/gateway/exchange", json=payload,
                                                 headers={"Authorization": f"Bearer {token}"})
                    response.raise_for_status()
                    result = None
                    command = response.json().get("command")
                    if command:
                        result = (await execute(adapter, command)) if values else {"id": command["id"], "status": "rejected"}
                except Exception:
                    # Never print exception text: HTTP libraries may include credentials/URLs.
                    log.warning("event=relay_exchange_failed")
                await asyncio.sleep(2)
        finally:
            adapter.close()


if __name__ == "__main__":
    asyncio.run(run())
