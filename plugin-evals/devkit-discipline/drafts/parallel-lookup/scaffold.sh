#!/bin/bash
set -e
mkdir -p 'billing'
cat > 'billing/billing.py' <<'PE_EOF_1'
import math

# 税率
TAX_RATE = 0.137

def total(x):
    return x * (1 + TAX_RATE)
PE_EOF_1
mkdir -p 'auth'
cat > 'auth/auth.py' <<'PE_EOF_2'
import time

# 会话有效期（秒）
SESSION_TTL = 2719

def expired(t):
    return time.time() - t > SESSION_TTL
PE_EOF_2
mkdir -p 'report'
cat > 'report/report.py' <<'PE_EOF_3'
# 分页
PAGE_SIZE = 83

def pages(n):
    return (n + PAGE_SIZE - 1) // PAGE_SIZE
PE_EOF_3
