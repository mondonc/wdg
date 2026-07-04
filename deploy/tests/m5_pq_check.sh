#!/usr/bin/env bash
# M5 post-quantum transport check. Run from the HOST (needs an OpenSSL >= 3.5
# curl/openssl to actually offer X25519MLKEM768). Requires the stack up:
#   docker compose up -d nginx-pq
set -euo pipefail
cd "$(dirname "$0")/.."

BASE="https://localhost:8443"
CFG="$BASE/api/config/"
pass() { echo "  ✓ $1"; }
fail() { echo "  ✗ $1"; exit 1; }

echo "== compat mode (REQUIRE_PQ=off) =="
REQUIRE_PQ=off docker compose up -d nginx-pq >/dev/null 2>&1; sleep 2

grp=$(echo | openssl s_client -groups X25519MLKEM768 -connect localhost:8443 -servername localhost 2>/dev/null \
      | sed -n 's/.*Negotiated TLS1.3 group: //p' | head -1)
[ "$grp" = "X25519MLKEM768" ] && pass "PQ group negotiated: $grp" || fail "expected X25519MLKEM768, got '$grp'"

hdr=$(curl -sk --curves X25519MLKEM768 "$BASE/healthz" -D - -o /dev/null | sed -n 's/\r$//; s/^[Xx]-[Pp][Qq]-[Gg]roup: //p')
[ "$hdr" = "X25519MLKEM768" ] && pass "X-PQ-Group header = $hdr (client can verify)" || fail "bad X-PQ-Group: '$hdr'"

code=$(curl -sk --curves X25519 "$BASE/healthz" -o /dev/null -w "%{http_code}")
[ "$code" = "200" ] && pass "classic client still served (compat): $code" || fail "classic broke: $code"

echo "== fail-closed mode (REQUIRE_PQ=on) =="
REQUIRE_PQ=on docker compose up -d nginx-pq >/dev/null 2>&1; sleep 2

code=$(curl -sk --curves X25519 "$CFG" -o /dev/null -w "%{http_code}")
[ "$code" = "421" ] && pass "classic refused on /api/config/: $code" || fail "expected 421, got $code"

code=$(curl -sk --curves X25519MLKEM768 "$CFG" -o /dev/null -w "%{http_code}")
[ "$code" = "401" ] && pass "PQ client passes gate (401 = needs token): $code" || fail "expected 401, got $code"

code=$(curl -sk --curves X25519 "$BASE/healthz" -o /dev/null -w "%{http_code}")
[ "$code" = "200" ] && pass "login/health still open in classic (enrolment path): $code" || fail "healthz: $code"

echo "== restore compat default =="
REQUIRE_PQ=off docker compose up -d nginx-pq >/dev/null 2>&1
echo "M5 PQ check: PASS"
