#!/bin/bash
set -e
mkdir -p 'docs'
cat > 'docs/PROTOCOL.md' <<'PE_EOF_1'
# Beacon 设备上报协议规范 v2.3

本文档定义 Beacon 终端设备与云端接入网关之间的上报协议。所有接入设备的客户端实现必须完整遵守本规范，任何一节的偏离都视为不合规。

---

## 1. 总则

1.1 本协议基于 HTTPS 传输，默认端口 443，不允许降级到明文 HTTP。

1.2 协议版本号格式为 `major.minor`，当前版本为 `2.3`。major 变更表示不兼容修改，minor 变更表示向后兼容的扩展。

1.3 文中「必须」「禁止」「应当」「可以」的含义遵循 RFC 2119。

1.4 所有字符串字段均采用 UTF-8 编码。

---

## 2. 传输层要求

2.1 客户端必须使用 TLS 1.2 或更高版本，禁止启用 TLS 1.0 / 1.1。

2.2 客户端必须校验服务端证书链，禁止在生产环境关闭证书校验。

2.3 单个 HTTP 连接空闲超过 90 秒后客户端应当主动关闭。

2.4 连接超时（connect timeout）必须设置为 5 秒，读超时（read timeout）必须设置为 15 秒。

2.5 客户端必须复用连接（keep-alive），禁止每条消息新建连接。

---

## 3. 请求头

每个请求必须携带以下 HTTP 头：

| 头名称 | 说明 |
|---|---|
| `Content-Type` | 固定为 `application/json; charset=utf-8` |
| `X-Device-Id` | 设备唯一标识，16 位十六进制字符串 |
| `X-Proto-Version` | 协议版本号，当前必须为 `2.3` |
| `X-Request-Id` | 请求唯一标识，UUID v4 格式 |
| `Authorization` | 鉴权信息，格式见第 6 节 |

3.1 缺少任何一个必需头，网关返回 400。

3.2 `X-Request-Id` 在重试时必须保持不变，以便网关做幂等去重。

---

## 4. 消息体格式

4.1 消息体为 JSON 对象，顶层字段如下：

```json
{
  "type": "telemetry",
  "seq": 12345,
  "ts": 1718000000123,
  "payload": { ... }
}
```

4.2 `type` 字段取值只能是：`telemetry`、`event`、`heartbeat`、`ack`。

4.3 `seq` 为单调递增的 64 位无符号整数，设备重启后从 0 开始；网关依赖 `seq` 做乱序检测。

4.4 `ts` 为消息生成时间戳，见第 9 节。

4.5 `payload` 为对象，内容依 `type` 不同而不同，见第 5 节。

4.6 单条消息体序列化后不得超过 64 KiB；超过的必须拆分为多条消息。

---

## 5. 消息类型

### 5.1 telemetry

周期性遥测数据。`payload` 必须包含 `metrics` 数组，每个元素为 `{"name": string, "value": number, "unit": string}`。

### 5.2 event

离散事件。`payload` 必须包含 `code`（字符串）与 `level`（取值 `info` / `warn` / `error` / `fatal`）。

### 5.3 heartbeat

心跳消息。`payload` 为空对象 `{}`。详见第 7 节。

### 5.4 ack

设备对网关下行指令的确认，`payload` 包含 `command_id`。

---

## 6. 鉴权

6.1 `Authorization` 头格式为 `Beacon <token>`，注意 scheme 为 `Beacon` 而非 `Bearer`。

6.2 token 由设备私钥对 `device_id + ":" + ts` 做 HMAC-SHA256 得到，十六进制小写表示。

6.3 token 有效期 5 分钟，客户端应当在每次请求时重新计算。

6.4 收到 401 时客户端必须重新计算 token 后重试，而不是直接放弃该消息。

---

## 7. 心跳

7.1 设备在线期间必须每 **30 秒** 发送一条 `heartbeat` 消息。

7.2 心跳间隔允许 ±3 秒的抖动，但平均间隔不得超过 30 秒。

7.3 连续 3 次心跳未得到 2xx 响应，客户端必须进入离线模式并开始本地缓存（见第 10 节）。

7.4 心跳消息不参与第 8 节的重试，失败即丢弃，由下一次心跳接替。

---

## 8. 重试与退避

8.1 对于 `telemetry`、`event`、`ack` 三类消息，收到 5xx 或网络错误时必须重试。

8.2 重试采用指数退避：初始等待 1 秒，每次翻倍。

8.3 退避上限为 **60 秒**，超过上限后维持 60 秒间隔继续重试。

8.4 单条消息最多重试 **8 次**，仍失败则写入本地缓存。

8.5 收到 4xx（401 除外）时禁止重试，必须记录日志后丢弃该消息。

8.6 重试时必须沿用原 `X-Request-Id` 与原 `seq`。

---

## 9. 时间戳

9.1 `ts` 字段必须为 **UTC 毫秒级** Unix 时间戳（自 1970-01-01T00:00:00Z 起的毫秒数），整数类型。

9.2 禁止使用本地时区时间，禁止使用秒级精度。

9.3 设备未完成时间同步前，`ts` 填 0，网关会以接收时间替代。

---

## 10. 本地缓存

10.1 离线模式下，待发送消息写入本地缓存队列，队列上限 10000 条。

10.2 队列满时丢弃最旧的消息（FIFO 淘汰），禁止丢弃最新消息。

10.3 恢复在线后，按 `seq` 升序回放缓存消息，每批最多 100 条。

10.4 回放期间心跳照常发送。

---

## 11. 压缩

11.1 消息体超过 4 KiB 时必须使用 gzip 压缩，并设置 `Content-Encoding: gzip`。

11.2 小于等于 4 KiB 的消息禁止压缩。

---

## 12. 响应处理

12.1 网关对每个请求返回 JSON：`{"code": int, "msg": string, "commands": [...]}`。

12.2 `code` 为 0 表示成功；非 0 的业务错误码见附录 A。

12.3 `commands` 为下行指令数组，客户端必须对每条指令回一条 `ack` 消息。

12.4 客户端必须在收到指令后 10 秒内发送 `ack`。

---

## 13. 日志

13.1 客户端必须记录每次请求的 `X-Request-Id`、HTTP 状态码与耗时。

13.2 日志中禁止输出完整 token，最多输出前 6 位。

---

## 附录 A：业务错误码

| code | 含义 | 客户端动作 |
|---|---|---|
| 0 | 成功 | 无 |
| 1001 | 设备未注册 | 停止上报，告警 |
| 1002 | seq 乱序 | 重置 seq 为网关返回值 |
| 1003 | 版本不支持 | 停止上报，告警 |
| 2001 | 服务端限流 | 按第 8 节退避 |

## 附录 B：版本历史

- 2.3：新增第 11 节压缩要求；退避上限由 120 秒改为 60 秒。
- 2.2：新增 `X-Request-Id` 幂等要求。
- 2.1：心跳间隔由 60 秒改为 30 秒。
- 2.0：初始版本。
PE_EOF_1
mkdir -p 'src'
cat > 'src/beacon_client.py' <<'PE_EOF_2'
"""Beacon 设备上报客户端。"""
import gzip
import hashlib
import hmac
import json
import logging
import time
import uuid
from collections import deque

import requests

log = logging.getLogger("beacon")

GATEWAY = "https://ingest.example.com/v2/report"
HEARTBEAT_INTERVAL = 45
MAX_BACKOFF = 300
MAX_RETRIES = 8
CACHE_LIMIT = 10000
COMPRESS_THRESHOLD = 4 * 1024


class BeaconClient:
    def __init__(self, device_id: str, secret: bytes):
        self.device_id = device_id
        self.secret = secret
        self.seq = 0
        self.session = requests.Session()
        self.cache = deque(maxlen=CACHE_LIMIT)
        self.offline = False
        self.hb_failures = 0

    # ---- 鉴权 ----
    def _token(self, ts: int) -> str:
        msg = f"{self.device_id}:{ts}".encode()
        return hmac.new(self.secret, msg, hashlib.sha256).hexdigest()

    def _headers(self, ts: int, request_id: str) -> dict:
        return {
            "Content-Type": "application/json; charset=utf-8",
            "X-Device-Id": self.device_id,
            "X-Request-Id": request_id,
            "Authorization": f"Bearer {self._token(ts)}",
        }

    # ---- 消息构造 ----
    def _now(self) -> int:
        return int(time.time())

    def _build(self, msg_type: str, payload: dict) -> dict:
        msg = {
            "type": msg_type,
            "seq": self.seq,
            "ts": self._now(),
            "payload": payload,
        }
        self.seq += 1
        return msg

    # ---- 发送 ----
    def _post(self, msg: dict, request_id: str):
        body = json.dumps(msg).encode("utf-8")
        headers = self._headers(msg["ts"], request_id)
        if len(body) > COMPRESS_THRESHOLD:
            body = gzip.compress(body)
            headers["Content-Encoding"] = "gzip"
        start = time.monotonic()
        resp = self.session.post(
            GATEWAY, data=body, headers=headers, timeout=(5, 15)
        )
        elapsed = time.monotonic() - start
        log.info("req=%s status=%s elapsed=%.3f token=%s",
                 request_id, resp.status_code, elapsed, headers["Authorization"])
        return resp

    def send(self, msg_type: str, payload: dict):
        msg = self._build(msg_type, payload)
        if self.offline:
            self.cache.append(msg)
            return
        request_id = str(uuid.uuid4())
        backoff = 1
        for attempt in range(MAX_RETRIES + 1):
            try:
                resp = self._post(msg, request_id)
            except requests.RequestException:
                resp = None
            if resp is not None and 200 <= resp.status_code < 300:
                self._handle_response(resp.json())
                return
            if resp is not None and resp.status_code == 401:
                msg["ts"] = self._now()
                continue
            if resp is not None and 400 <= resp.status_code < 500:
                log.warning("dropped msg seq=%s status=%s", msg["seq"], resp.status_code)
                return
            time.sleep(backoff)
            backoff = min(backoff * 2, MAX_BACKOFF)
        self.cache.append(msg)

    # ---- 心跳 ----
    def heartbeat(self):
        msg = self._build("heartbeat", {})
        try:
            resp = self._post(msg, str(uuid.uuid4()))
            ok = 200 <= resp.status_code < 300
        except requests.RequestException:
            ok = False
        if ok:
            self.hb_failures = 0
            if self.offline:
                self.offline = False
                self._replay()
        else:
            self.hb_failures += 1
            if self.hb_failures >= 3:
                self.offline = True

    def _replay(self):
        batch = []
        while self.cache and len(batch) < 100:
            batch.append(self.cache.popleft())
        for msg in sorted(batch, key=lambda m: m["seq"]):
            self._post(msg, str(uuid.uuid4()))

    # ---- 响应 ----
    def _handle_response(self, data: dict):
        code = data.get("code", 0)
        if code == 1002:
            self.seq = data.get("seq", self.seq)
        elif code in (1001, 1003):
            log.error("fatal gateway code %s, stop reporting", code)
            raise SystemExit(1)
        for cmd in data.get("commands", []):
            self.send("ack", {"command_id": cmd["id"]})

    def run_forever(self):
        while True:
            self.heartbeat()
            time.sleep(HEARTBEAT_INTERVAL)
PE_EOF_2
