#!/bin/sh
# HA failover checks, run from the repo root against the running dev stack
# (make up && make seed first). Exercises what docs/DAT.md §5 promises:
#   1. gateway agent fails over from control-plane-int-1 to -int-2 (≤ 1 poll)
#   2. the external pair keeps answering behind the cp-ext alias with one
#      instance down (DNS round-robin standing in for the RR/VIP)
#   3. everything recovers once the stopped instances come back
# Like m5_pq_check.sh, this drives docker compose from the host — it stops
# and restarts containers, so it lives outside run_all.py on purpose.
set -e

COMPOSE="docker compose -f deploy/docker-compose.yml"
fail() { echo "✗ $1"; exit 1; }

# Always bring the stopped instances back, even on failure.
trap '$COMPOSE start control-plane-int-1 control-plane-ext-1 >/dev/null 2>&1 || true' EXIT

echo "== agent failover: control-plane-int-1 -> -int-2 =="
$COMPOSE --profile tunnel up -d wdgw-a >/dev/null 2>&1
sleep 8
$COMPOSE exec -T wdgw-a sh -c "wg show wg0 listen-port" >/dev/null 2>&1 \
    || fail "wdgw-a has no wg0 interface: agent never completed a sync"

$COMPOSE stop control-plane-int-1 >/dev/null 2>&1
sleep 12
docker logs wdg-wdgw-a-1 --since 14s 2>&1 | grep -q "switched to control plane http://control-plane-int-2:8000" \
    || fail "agent did not switch to control-plane-int-2"
LAST=$(docker logs wdg-wdgw-a-1 --since 6s 2>&1 | grep -c "sync failed" || true)
[ "$LAST" -eq 0 ] || fail "agent still failing after the switch ($LAST errors)"
echo "  ✓ agent switched to int-2 and keeps syncing (int-1 down)"

echo "== external pair: cp-ext alias with ext-1 down =="
$COMPOSE stop control-plane-ext-1 >/dev/null 2>&1
sleep 3
$COMPOSE exec -T control-plane-admin python -c "
import urllib.request
for i in range(5):
    r = urllib.request.urlopen('http://cp-ext:8000/healthz', timeout=5)
    assert r.status == 200, r.status
print('  ✓ 5/5 requests answered by the surviving external instance')
" || fail "cp-ext alias stopped answering with ext-1 down"

echo "== recovery =="
$COMPOSE start control-plane-int-1 control-plane-ext-1 >/dev/null 2>&1
sleep 12
LAST=$(docker logs wdg-wdgw-a-1 --since 8s 2>&1 | grep -c "sync failed" || true)
[ "$LAST" -eq 0 ] || fail "sync errors after restart ($LAST)"
echo "  ✓ no sync errors after both instances returned"

echo "HA failover check: PASS"
