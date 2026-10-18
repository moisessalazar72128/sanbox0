"""Single-process, single-gateway relay. No arbitrary PLC address/protocol API."""
import hmac
import json
import logging
import os
import time
import uuid
from collections import deque
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from .models import Exchange, Setpoint
from .security import hash_password, verify_password

log = logging.getLogger("audit")
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s %(message)s')
basic = HTTPBasic(auto_error=False)


def create_app(users: dict, token: str, allow_writes: bool = False, clock=time.time):
    if len(token) < 32 or not users:
        raise ValueError("A strong gateway token and at least one user are required")
    for user in users.values():
        if user.get("role") not in {"viewer", "operator"} or not user.get("password_hash", "").startswith("scrypt$"):
            raise ValueError("Invalid user configuration")
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    state = {"sample": None, "received": 0, "pending": None, "command": None}
    # Bounded global failure budget avoids unbounded attacker-controlled IP/user maps.
    failures = deque(maxlen=20)
    dummy = hash_password(uuid.uuid4().hex)

    @app.middleware("http")
    async def harden(request: Request, call_next):
        response = await call_next(request)
        response.headers.update({
            "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
            "Referrer-Policy": "no-referrer", "Strict-Transport-Security": "max-age=31536000",
        })
        return response

    async def authenticate(credentials: HTTPBasicCredentials | None = Depends(basic)):
        now = clock()
        while failures and now - failures[0] > 60:
            failures.popleft()
        if len(failures) >= 20:
            raise HTTPException(429, "Authentication rate limit", headers={"Retry-After": "60"})
        if credentials is None:
            raise HTTPException(401, "Authentication required", headers={"WWW-Authenticate": 'Basic realm="PLC Access"'})
        user = users.get(credentials.username)
        valid = verify_password(credentials.password, user["password_hash"] if user else dummy)
        if not user or not valid:
            failures.append(now)
            log.warning("event=login_denied")
            raise HTTPException(401, "Invalid credentials", headers={"WWW-Authenticate": 'Basic realm="PLC Access"'})
        return {"name": credentials.username, "role": user["role"]}

    async def gateway(authorization: str = Header(default="")):
        if not hmac.compare_digest(authorization.encode(), f"Bearer {token}".encode()):
            log.warning("event=gateway_denied")
            raise HTTPException(401, "Invalid gateway credential")

    def expire():
        pending = state["pending"]
        if pending and pending["expires_at"] <= clock():
            state["command"] = {**pending, "status": "expired"}
            state["pending"] = None

    @app.get("/healthz")
    async def health():
        return {"status": "ok"}

    @app.get("/", response_class=HTMLResponse)
    async def index(user=Depends(authenticate)):
        return Path(__file__).with_name("static").joinpath("index.html").read_text()

    @app.get("/app.js")
    async def js(user=Depends(authenticate)):
        return FileResponse(Path(__file__).with_name("static") / "app.js", media_type="text/javascript")

    @app.get("/style.css")
    async def css(user=Depends(authenticate)):
        return FileResponse(Path(__file__).with_name("static") / "style.css", media_type="text/css")

    @app.get("/api/status")
    async def status(user=Depends(authenticate)):
        log.info("event=telemetry_read user=%s", json.dumps(user["name"]))
        expire()
        age = max(0, clock() - state["received"]) if state["sample"] else None
        fresh = age is not None and age <= 10 and state["sample"]["quality"] == "good"
        return {"user": user, "sample": state["sample"], "age_seconds": age,
                "fresh": fresh, "writes_enabled": allow_writes, "command": state["command"]}

    @app.post("/api/setpoint", status_code=202)
    async def setpoint(body: Setpoint, request: Request, user=Depends(authenticate)):
        # Basic credentials are browser-managed: require a non-simple custom header and JSON.
        # There is no CORS middleware; cross-origin preflights are rejected.
        if request.headers.get("X-PLC-Action") != "setpoint":
            raise HTTPException(403, "Action header required")
        if user["role"] != "operator" or not allow_writes:
            log.warning("event=write_denied role=%s", user["role"])
            raise HTTPException(403, "Writes disabled or role denied")
        sample = state["sample"]
        if not sample or clock() - state["received"] > 10 or sample["quality"] != "good" or not sample["writable"]:
            raise HTTPException(409, "Gateway unavailable or read-only")
        expire()
        if state["pending"] or (state["command"] and state["command"]["status"] == "delivered" and clock() < state["command"]["expires_at"] + 10):
            raise HTTPException(409, "A command is already in flight")
        cmd = {"id": str(uuid.uuid4()), "value": body.value, "expires_at": clock() + 5}
        state["pending"] = cmd
        state["command"] = {**cmd, "status": "queued"}
        log.info("event=command_queued id=%s value=%s user=%s", cmd["id"], cmd["value"], json.dumps(user["name"]))
        return cmd

    @app.post("/api/gateway/exchange", dependencies=[Depends(gateway)])
    async def exchange(body: Exchange):
        if (body.quality == "good") != (body.values is not None):
            raise HTTPException(422, "Quality and values disagree")
        state["sample"] = body.model_dump(exclude={"result"})
        state["received"] = clock()
        if body.result and state["command"] and body.result.id == state["command"]["id"]:
            state["command"]["status"] = body.result.status
            log.info("event=command_result id=%s status=%s", body.result.id, body.result.status)
        expire()
        cmd = state["pending"]
        # Remove before replying: delivery is at most once; lost response is UNKNOWN, never retried.
        state["pending"] = None
        if cmd:
            state["command"] = {**cmd, "status": "delivered"}
            log.info("event=command_delivered id=%s", cmd["id"])
        return {"command": cmd}

    return app


def from_env():
    return create_app(json.loads(Path(os.environ["USERS_FILE"]).read_text()),
                      Path(os.environ["GATEWAY_TOKEN_FILE"]).read_text().strip(),
                      os.getenv("RELAY_ALLOW_WRITES", "false").lower() == "true")
