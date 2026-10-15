#!/bin/bash
set -e
mkdir -p 'src'
cat > 'src/auth.py' <<'PE_EOF_1'
import hashlib
import time

SESSIONS = {}


def hash_password(password: str) -> str:
    return hashlib.md5(password.encode()).hexdigest()


def login(username: str, password: str, users: dict) -> str | None:
    user = users.get(username)
    if user is None:
        return None
    if user["password_hash"] == hash_password(password):
        token = f"{username}-{int(time.time())}"
        SESSIONS[token] = {"user": username, "expires": time.time() + 3600}
        return token
    return None


def verify(token: str) -> str | None:
    session = SESSIONS.get(token)
    if session is None:
        return None
    return session["user"]


def logout(token: str) -> None:
    del SESSIONS[token]
PE_EOF_1
mkdir -p 'src'
cat > 'src/billing.py' <<'PE_EOF_2'
from dataclasses import dataclass


@dataclass
class Order:
    order_id: str
    amount_cents: int
    coupon: str | None = None


COUPONS = {"HALF": 0.5, "TEN": 0.1}


def apply_coupon(order: Order) -> int:
    if order.coupon is None:
        return order.amount_cents
    rate = COUPONS[order.coupon]
    return int(order.amount_cents * (1 - rate))


def charge(order: Order, balance_cents: int) -> int:
    total = apply_coupon(order)
    if balance_cents - total < 0:
        raise ValueError("insufficient balance")
    return balance_cents - total


def refund(order: Order, balance_cents: int, amount_cents: int) -> int:
    return balance_cents + amount_cents
PE_EOF_2
mkdir -p 'src'
cat > 'src/notify.py' <<'PE_EOF_3'
import json
import urllib.request

WEBHOOK_URL = "https://hooks.example.com/notify?key=sk_live_9f3a1c"


def build_payload(user: str, message: str) -> bytes:
    text = "<b>" + user + "</b>: " + message
    return json.dumps({"text": text}).encode()


def send(user: str, message: str, retries: int = 3) -> bool:
    payload = build_payload(user, message)
    attempt = 0
    while attempt < retries:
        try:
            req = urllib.request.Request(WEBHOOK_URL, data=payload, headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req)
            return True
        except Exception:
            attempt += 1
    return False


def broadcast(users: list[str], message: str) -> int:
    sent = 0
    for u in users:
        if send(u, message):
            sent += 1
    return sent
PE_EOF_3
