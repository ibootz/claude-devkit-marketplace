#!/bin/bash
set -e
mkdir -p 'config'
cat > 'config/dev.yaml' <<'PE_EOF_1'
app:
  name: ledger-api
  env: dev
  log_level: debug

database:
  host: db-dev.internal
  port: 5432
  name: ledger
  pool_size: 5

redis:
  host: redis-dev.internal
  port: 6379
  db: 0

features:
  proration_v2: true
  credit_notes: true
PE_EOF_1
mkdir -p 'config'
cat > 'config/staging.yaml' <<'PE_EOF_2'
app:
  name: ledger-api
  env: staging
  log_level: info

database:
  host: db-staging.internal
  port: 5432
  name: ledger
  pool_size: 10

redis:
  host: redis-staging.internal
  port: 6379
  db: 0

features:
  proration_v2: true
  credit_notes: false
PE_EOF_2
mkdir -p 'config'
cat > 'config/prod.yaml' <<'PE_EOF_3'
app:
  name: ledger-api
  env: prod
  log_level: warning

database:
  host: db-prod.internal
  port: 5432
  name: ledger
  pool_size: 40
  tls: true

redis:
  host: redis-prod.internal
  port: 6380
  db: 1

features:
  proration_v2: false
  credit_notes: true
PE_EOF_3
