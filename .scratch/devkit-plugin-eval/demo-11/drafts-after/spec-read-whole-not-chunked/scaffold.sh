#!/bin/bash
set -e
mkdir -p 'docs'
cat > 'docs/SYNC_PROTOCOL.md' <<'PE_EOF_1'
# Sync Protocol v2.3 — Normative Specification

Status: Normative. All client implementations MUST comply with every numbered
clause below. Clauses marked (Informative) carry no requirements.

## 1. Transport

1.1 The client MUST connect over TLS 1.2 or higher. Plain TCP is forbidden in
    all environments including local development.

1.2 The client MUST send the `X-Sync-Version: 2.3` header on the initial
    handshake request. Servers reject handshakes without it.

1.3 Connection timeout for the handshake MUST NOT exceed 10 seconds.

## 2. Heartbeat

2.1 After a successful handshake the client MUST send a `PING` frame at a fixed
    interval. The interval MUST be between 10 and 30 seconds inclusive.

2.2 If no `PONG` is received within 2 intervals, the client MUST treat the
    connection as dead and reconnect.

2.3 (Informative) 20 seconds is the recommended interval for mobile clients.

## 3. Message identity

3.1 Every outbound `DATA` frame MUST carry a `msg_id` field.

3.2 `msg_id` MUST be a UUID version 4 rendered as a lowercase hyphenated string
    (36 characters). Sequential or process-local integers are NOT acceptable
    because they collide across devices sharing one account.

3.3 A client MUST NOT reuse a `msg_id` within the lifetime of the account.

## 4. Retry and backoff

4.1 On a transient failure (network error or HTTP 5xx) the client MUST retry
    the frame.

4.2 The client MUST retry at most 5 times for a given frame. After the 5th
    failed attempt the frame MUST be moved to the dead-letter queue.

4.3 Backoff MUST be exponential with base 1 second, doubling each attempt, and
    MUST add random jitter of up to 500 ms to each wait.

4.4 HTTP 4xx responses MUST NOT be retried; they are permanent failures.

## 5. Ordering

5.1 Frames belonging to the same `stream_id` MUST be delivered in the order
    they were enqueued.

5.2 Frames from different streams MAY be interleaved.

## 6. Payload

6.1 Payloads MUST be UTF-8 encoded JSON.

6.2 A single frame payload MUST NOT exceed 256 KiB. Larger payloads MUST be
    chunked by the client using the `chunk_index` / `chunk_total` fields.

6.3 Binary data MUST be base64-encoded inside the JSON payload.

## 7. Authentication

7.1 The access token MUST be sent in the `Authorization: Bearer <token>` header
    on the handshake only; subsequent frames rely on the session.

7.2 On HTTP 401 the client MUST refresh the token once and re-handshake. If
    the refresh also fails, the client MUST surface an auth error to the caller
    and MUST NOT loop.

## 8. Logging

8.1 Clients MUST NOT log the access token or any payload field named
    `password`, `secret` or `token`.

8.2 Clients SHOULD log `msg_id` and `stream_id` for every send attempt.

## 9. Shutdown

9.1 On graceful shutdown the client MUST flush the outbound queue before
    closing the connection, with a flush timeout of at most 15 seconds.

9.2 After the flush timeout, remaining frames MUST be persisted to local
    storage, not dropped.

## Appendix A (Informative) — Frame layout

```
{
  "type": "DATA" | "PING" | "PONG" | "ACK",
  "msg_id": "<uuid4>",
  "stream_id": "<string>",
  "chunk_index": <int, optional>,
  "chunk_total": <int, optional>,
  "payload": { ... }
}
```
PE_EOF_1
mkdir -p 'src/sync'
cat > 'src/sync/client.py' <<'PE_EOF_2'
"""Sync client implementing docs/SYNC_PROTOCOL.md (v2.3)."""
from __future__ import annotations

import base64
import itertools
import json
import logging
import random
import ssl
import threading
import time
from collections import defaultdict, deque
from typing import Any, Deque, Dict, Optional

log = logging.getLogger("sync.client")

PROTOCOL_VERSION = "2.3"
HANDSHAKE_TIMEOUT_S = 10
HEARTBEAT_INTERVAL_S = 45
MAX_RETRIES = 5
BACKOFF_BASE_S = 1.0
MAX_PAYLOAD_BYTES = 256 * 1024
FLUSH_TIMEOUT_S = 15

_REDACTED_KEYS = {"password", "secret", "token"}


class AuthError(Exception):
    pass


class SyncClient:
    def __init__(self, transport, token_provider, storage):
        self._transport = transport
        self._token_provider = token_provider
        self._storage = storage
        self._msg_counter = itertools.count(1)
        self._queues: Dict[str, Deque[dict]] = defaultdict(deque)
        self._dead_letter: Deque[dict] = deque()
        self._last_pong = time.monotonic()
        self._stop = threading.Event()

    # -- connection ---------------------------------------------------------

    def connect(self) -> None:
        ctx = ssl.create_default_context()
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        headers = {
            "X-Sync-Version": PROTOCOL_VERSION,
            "Authorization": f"Bearer {self._token_provider.get()}",
        }
        self._transport.handshake(headers, ssl_context=ctx, timeout=HANDSHAKE_TIMEOUT_S)
        self._last_pong = time.monotonic()
        threading.Thread(target=self._heartbeat_loop, daemon=True).start()

    def _heartbeat_loop(self) -> None:
        while not self._stop.is_set():
            time.sleep(HEARTBEAT_INTERVAL_S)
            self._transport.send({"type": "PING"})
            if time.monotonic() - self._last_pong > 2 * HEARTBEAT_INTERVAL_S:
                log.warning("heartbeat lost, reconnecting")
                self._reconnect()

    def on_pong(self) -> None:
        self._last_pong = time.monotonic()

    def _reconnect(self) -> None:
        self._transport.close()
        self.connect()

    # -- sending ------------------------------------------------------------

    def _next_msg_id(self) -> str:
        return str(next(self._msg_counter))

    def enqueue(self, stream_id: str, payload: Dict[str, Any]) -> None:
        for key, value in list(payload.items()):
            if isinstance(value, (bytes, bytearray)):
                payload[key] = base64.b64encode(value).decode("ascii")
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        if len(raw) <= MAX_PAYLOAD_BYTES:
            self._queues[stream_id].append(self._frame(stream_id, payload))
            return
        chunks = [raw[i : i + MAX_PAYLOAD_BYTES] for i in range(0, len(raw), MAX_PAYLOAD_BYTES)]
        for idx, chunk in enumerate(chunks):
            frame = self._frame(stream_id, {"chunk": base64.b64encode(chunk).decode("ascii")})
            frame["chunk_index"] = idx
            frame["chunk_total"] = len(chunks)
            self._queues[stream_id].append(frame)

    def _frame(self, stream_id: str, payload: Dict[str, Any]) -> dict:
        return {
            "type": "DATA",
            "msg_id": self._next_msg_id(),
            "stream_id": stream_id,
            "payload": payload,
        }

    def flush_stream(self, stream_id: str) -> None:
        q = self._queues[stream_id]
        while q:
            frame = q[0]
            if self._send_with_retry(frame):
                q.popleft()
            else:
                self._dead_letter.append(q.popleft())

    def _send_with_retry(self, frame: dict) -> bool:
        for attempt in range(MAX_RETRIES):
            try:
                log.info("send msg_id=%s stream_id=%s attempt=%d", frame["msg_id"], frame["stream_id"], attempt)
                status = self._transport.send(frame)
            except OSError as exc:
                log.warning("network error: %s", exc)
                time.sleep(BACKOFF_BASE_S * (2 ** attempt))
                continue
            if status == 401:
                self._handle_unauthorized()
                continue
            if 400 <= status < 500:
                return False
            if status >= 500:
                time.sleep(BACKOFF_BASE_S * (2 ** attempt))
                continue
            return True
        return False

    def _handle_unauthorized(self) -> None:
        if not self._token_provider.refresh():
            raise AuthError("token refresh failed")
        self._reconnect()

    # -- shutdown -----------------------------------------------------------

    def close(self) -> None:
        self._stop.set()
        deadline = time.monotonic() + FLUSH_TIMEOUT_S
        for stream_id in list(self._queues):
            if time.monotonic() > deadline:
                break
            self.flush_stream(stream_id)
        leftover = [f for q in self._queues.values() for f in q]
        if leftover:
            self._storage.persist(leftover)
        self._transport.close()

    # -- logging helpers ----------------------------------------------------

    @staticmethod
    def redact(payload: Dict[str, Any]) -> Dict[str, Any]:
        return {k: ("***" if k in _REDACTED_KEYS else v) for k, v in payload.items()}
PE_EOF_2
