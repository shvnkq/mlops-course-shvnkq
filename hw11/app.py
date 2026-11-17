"""HW11 deployment of the /generate, /health and /ready API from HW8–10."""
import asyncio
from collections import OrderedDict
from contextlib import aclosing, asynccontextmanager, suppress
import hashlib
import hmac
import json
import os
from pathlib import Path
import time
from typing import Literal
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
from pydantic import BaseModel, Field

POD = os.getenv("POD_NAME", "local")
VERSION = os.getenv("MODEL_VERSION", "A")
EXPECTED_SHA = os.environ.get("MODEL_SHA256", "")
WARMUP = float(os.getenv("WARMUP_SECONDS", "20"))
EARLY = os.getenv("EARLY_READY", "false") == "true"
SLOTS = int(os.getenv("SLOTS", "1"))
QUEUE = int(os.getenv("QUEUE", "3"))
CACHE = int(os.getenv("CACHE_SIZE", "8"))
HIT = float(os.getenv("HIT_SECONDS", ".18"))
MISS = float(os.getenv("MISS_SECONDS", ".44"))
MODE = "simulated"
BUCKETS = (.01,.025,.05,.1,.15,.2,.25,.3,.4,.5,.6,.8,1,1.25,1.5,2,3,5,10,15,25)
TTFC = Histogram("hw11_ttfc_seconds", "Server time to first content chunk, successful requests", buckets=BUCKETS)
TOTAL = Histogram("hw11_response_seconds", "Full server time, successful requests", buckets=BUCKETS)
WAIT = Histogram("hw11_queue_seconds", "Server wait, successful requests", buckets=BUCKETS)
GAP = Histogram("hw11_inter_chunk_seconds", "Server time between content chunks", buckets=BUCKETS)
RUNNING = Gauge("hw11_running", "Requests occupying a slot")
WAITING = Gauge("hw11_waiting", "Requests in the admission queue")
READY = Gauge("hw11_backend_ready", "Validated and warmed backend, except during drain")
REQUESTS = Counter("hw11_requests", "Terminal outcomes", ["outcome"])
for outcome in ("ok", "rejected", "unavailable", "aborted"):
    REQUESTS.labels(outcome)
CACHE_LOOKUPS = Counter("hw11_cache", "Local prefix cache lookups", ["result"])
CACHE_LOOKUPS.labels("hit")
CACHE_LOOKUPS.labels("miss")


def log(event, **fields):
    print(json.dumps({"ts":time.time(), "event":event, "pod":POD,
                      "configured_version":VERSION, **fields}, ensure_ascii=False), flush=True)


class Turn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=4096)


class Generate(BaseModel):
    prompt: str = Field(min_length=1, max_length=4096)
    max_new_tokens: Literal[32] = 32
    session_id: str = Field(default="", max_length=96)
    history: list[Turn] = Field(default_factory=list, max_length=12)
    stream: bool = False
    chunks: int = Field(default=3, ge=1, le=12)
    chunk_ms: int = Field(default=60, ge=10, le=1000)
    cpu_ms: int = Field(default=0, ge=0, le=180)


class SimulatedBackend:
    """A verified artifact, bounded per-process LRU and no session storage."""

    def __init__(self):
        self.artifact = None
        self.sha = ""
        self.error = None
        self.warmed = False
        self.draining = False
        self.running = 0
        self.waiting = 0
        self.slots = asyncio.Semaphore(SLOTS)
        self.cache = OrderedDict()

    async def warmup(self):
        log("warmup_started")
        try:
            data = Path("/model/model.json").read_bytes()
            self.sha = hashlib.sha256(data).hexdigest()
            if not hmac.compare_digest(self.sha, EXPECTED_SHA):
                raise ValueError("artifact SHA-256 mismatch")
            artifact = json.loads(data)
            if artifact["version"] != VERSION:
                raise ValueError("artifact version mismatch")
            self.artifact = artifact
            await asyncio.sleep(WARMUP)
            self.warmed = True
            READY.set(1)
            log("warmup_finished", loaded_version=VERSION, sha256=self.sha)
        except (ValueError, OSError, KeyError) as exc:
            self.error = str(exc)
            log("warmup_failed", error=self.error, sha256=self.sha)

    def lookup(self, prompt):
        key = prompt.partition("|")[0]
        hit = key in self.cache
        self.cache[key] = True
        self.cache.move_to_end(key)
        if len(self.cache) > CACHE:
            self.cache.popitem(last=False)
        CACHE_LOOKUPS.labels("hit" if hit else "miss").inc()
        return hit


def burn_cpu(milliseconds):
    deadline = time.thread_time() + milliseconds / 1000
    while time.thread_time() < deadline:
        hashlib.pbkdf2_hmac("sha256", b"hw11", b"load", 3000)


state = SimulatedBackend()


@asynccontextmanager
async def lifespan(_app):
    task = asyncio.create_task(state.warmup())
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


app = FastAPI(lifespan=lifespan)


@app.get("/health")
async def health():
    return {"alive":True, "backend_mode":MODE, "pod":POD,
            "loaded_version":VERSION if state.artifact else None}


@app.get("/ready")
async def ready():
    available = state.warmed and not state.draining
    return JSONResponse({"ready":available,"error":state.error,"pod":POD,
                         "backend_mode":MODE,"model_id":VERSION if state.artifact else None},
                        status_code=200 if available else 503)


@app.get("/metrics")
async def metrics():
    return Response(generate_latest(), headers={"Content-Type":CONTENT_TYPE_LATEST})


@app.post("/internal/{operation}")
async def control(operation: str, request: Request):
    if request.client.host != "127.0.0.1":
        return Response(status_code=403)
    if operation == "drain":
        state.draining = True
        READY.set(0)
        log("drain_started", running=state.running, waiting=state.waiting)
        await asyncio.sleep(3)
    elif operation == "clear-cache":
        state.cache.clear()
        log("cache_cleared")
    else:
        return Response(status_code=404)
    return Response(status_code=204)


def ndjson(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n"


@app.post("/generate")
async def generate(payload: Generate, request: Request):
    started = time.monotonic()
    request_id = request.headers.get("x-request-id", str(uuid.uuid4()))[:120]
    version = VERSION if state.artifact else ""
    info = {"request_id":request_id, "pod":POD, "model_id":version,
            "runtime_sha256":state.sha, "backend_mode":MODE, "warmed":state.warmed}
    trace = {**info, "session_id":payload.session_id, "client_ip":request.client.host}
    headers = {"X-Request-ID":request_id,"X-Pod":POD,"X-Model-Version":version,
               "X-Backend-Mode":MODE,"X-Warmed":str(state.warmed).lower()}
    log("received", **trace, running=state.running, waiting=state.waiting)

    def decline(status, outcome):
        REQUESTS.labels(outcome).inc()
        log("finished", **trace, outcome=outcome, status=status)
        return JSONResponse({**info, "error":outcome}, status_code=status, headers=headers)

    if not state.artifact or (not EARLY and not state.warmed):
        return decline(503, "unavailable")
    if state.running + state.waiting >= SLOTS + QUEUE:
        return decline(429, "rejected")

    state.waiting += 1
    WAITING.inc()

    async def fragments():
        acquired = False
        outcome = "aborted"
        emitted = 0
        try:
            await state.slots.acquire()
            acquired = True
            state.waiting -= 1
            WAITING.dec()
            state.running += 1
            RUNNING.inc()
            dequeued = time.monotonic()
            wait = dequeued - started
            hit = state.lookup(payload.prompt)
            await asyncio.sleep(HIT if hit else MISS)
            if payload.cpu_ms:
                await asyncio.to_thread(burn_cpu, payload.cpu_ms)
            first = last = time.monotonic()
            marker = next((turn.content for turn in payload.history if turn.role == "user"), "")
            for index in range(payload.chunks):
                if index:
                    await asyncio.sleep(payload.chunk_ms / 1000)
                    now = time.monotonic()
                    GAP.observe(now - last)
                    last = now
                text = (f"{state.artifact['response']} {marker}".rstrip() if index == 0
                        else f" · часть {index + 1}")
                emitted += 1
                yield {**info, "type":"chunk", "index":index, "text":text,
                       "queue_seconds":wait,"cache_hit":hit}
            total = time.monotonic() - started
            yield {**info, "type":"done", "chunks":emitted, "total_seconds":total}
            outcome = "ok"
            TTFC.observe(first - started)
            TOTAL.observe(total)
            WAIT.observe(wait)
        finally:
            REQUESTS.labels(outcome).inc()
            log("finished", **trace, outcome=outcome, status=200, chunks=emitted)
            if acquired:
                state.running -= 1
                RUNNING.dec()
                state.slots.release()
            else:
                state.waiting -= 1
                WAITING.dec()

    if payload.stream:
        async def stream():
            async with aclosing(fragments()) as response:
                async for fragment in response:
                    yield ndjson(fragment)

        return StreamingResponse(stream(), media_type="application/x-ndjson", headers=headers)

    parts = [fragment async for fragment in fragments()]
    return JSONResponse({**info, "answer":"".join(p["text"] for p in parts[:-1]),
                         "chunks":len(parts)-1,"queue_seconds":parts[0]["queue_seconds"],
                         "total_seconds":parts[-1]["total_seconds"]}, headers=headers)
