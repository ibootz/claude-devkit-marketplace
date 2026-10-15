#!/bin/bash
set -e
cat > 'README.md' <<'PE_EOF_1'
# ledger-api

内部账本服务。

## 部署流程

1. 合并到 `main` 后等待 CI 通过。
2. 执行 `scripts/rotate_keys.sh` 轮换网关密钥。
3. 执行 `scripts/backfill_invoices.py --since <date>` 补齐历史账单。
4. 滚动重启 worker。
5. 用 `scripts/export_ledger.py` 导出当日台账核对。
PE_EOF_1
mkdir -p 'src/app'
cat > 'src/app/__init__.py' <<'PE_EOF_2'

PE_EOF_2
mkdir -p 'src/app'
cat > 'src/app/config.py' <<'PE_EOF_3'
import os

DEFAULT_TIMEOUT = 8
DEFAULT_POOL_SIZE = int(os.environ.get("POOL_SIZE", "10"))


def load() -> dict:
    return {
        "timeout": int(os.environ.get("TIMEOUT", DEFAULT_TIMEOUT)),
        "pool_size": DEFAULT_POOL_SIZE,
    }
PE_EOF_3
mkdir -p 'src/app'
cat > 'src/app/handlers.py' <<'PE_EOF_4'
from .config import load


def handle_charge(payload: dict) -> dict:
    cfg = load()
    print("DEBUG payload", payload)
    return {"ok": True, "timeout": cfg["timeout"]}


def handle_refund(payload: dict) -> dict:
    return {"ok": True}
PE_EOF_4
mkdir -p 'src/app'
cat > 'src/app/worker.py' <<'PE_EOF_5'
import time


def run_forever() -> None:
    while True:
        print("tick")
        time.sleep(5)
PE_EOF_5
mkdir -p 'scripts'
cat > 'scripts/backfill_invoices.py' <<'PE_EOF_6'
#!/usr/bin/env python3
"""Backfill invoices for customers activated before the cutover.

Usage:
    backfill_invoices.py --since YYYY-MM-DD [--dry-run] [--batch N]

Options:
    --since     Only customers activated on/after this date.
    --dry-run   Print what would be created without writing.
    --batch     Customers per transaction (default 200).
"""
import argparse


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--since", required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--batch", type=int, default=200)
    args = parser.parse_args()
    print(args)


if __name__ == "__main__":
    main()
PE_EOF_6
mkdir -p 'scripts'
cat > 'scripts/rotate_keys.sh' <<'PE_EOF_7'
#!/usr/bin/env bash
# Rotate the payment gateway API key and restart workers.
#
# Usage:
#   rotate_keys.sh <env> [--no-restart]
#
# Arguments:
#   <env>          One of dev, staging, prod.
#   --no-restart   Write the new key but skip the worker restart.
set -euo pipefail

ENV_NAME="${1:?env required}"
echo "rotating key for ${ENV_NAME}"
PE_EOF_7
mkdir -p 'scripts'
cat > 'scripts/export_ledger.py' <<'PE_EOF_8'
#!/usr/bin/env python3
"""Export the ledger for one day as CSV.

Usage:
    export_ledger.py --date YYYY-MM-DD --out PATH [--currency CNY]

Options:
    --date       Business day to export.
    --out        Destination CSV path.
    --currency   Filter to a single currency (default: all).
"""
import argparse


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--currency")
    args = parser.parse_args()
    print(args)


if __name__ == "__main__":
    main()
PE_EOF_8
