#!/bin/bash
set -e
mkdir -p billing auth report
printf 'import math\n\n# 税率\nTAX_RATE = 0.137\n\ndef total(x):\n    return x * (1 + TAX_RATE)\n' > billing/billing.py
printf 'import time\n\n# 会话有效期（秒）\nSESSION_TTL = 2719\n\ndef expired(t):\n    return time.time() - t > SESSION_TTL\n' > auth/auth.py
printf '# 分页\nPAGE_SIZE = 83\n\ndef pages(n):\n    return (n + PAGE_SIZE - 1) // PAGE_SIZE\n' > report/report.py
