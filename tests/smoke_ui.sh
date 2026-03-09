#!/usr/bin/env bash
# smoke_ui.sh — Dashboard & API route smoke test
# Usage: DASH_URL=http://... API_URL=http://... ./tests/smoke_ui.sh

set -euo pipefail

DASH_URL="${DASH_URL:-http://127.0.0.1:5052}"
API_URL="${API_URL:-http://127.0.0.1:5050}"
API_TOKEN="${API_TOKEN:-d3FlLSCvNcxEGDexTReZmdJfP7JIwnB0OtoTrsklCYE}"

PASS=0; FAIL=0; TOTAL=0

check() {
  local label="$1" url="$2" expect="${3:-200}"
  TOTAL=$((TOTAL+1))
  code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 -H "Authorization: Bearer $API_TOKEN" "$url" 2>/dev/null || echo "000")
  if [ "$code" = "$expect" ]; then
    echo "✅ $code $label"
    PASS=$((PASS+1))
  else
    echo "❌ $code $label (expected $expect)"
    FAIL=$((FAIL+1))
  fi
}

check_post() {
  local label="$1" url="$2" data="${3:-}" expect="${4:-200}"
  TOTAL=$((TOTAL+1))
  code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 -X POST -H "Authorization: Bearer $API_TOKEN" -d "$data" "$url" 2>/dev/null || echo "000")
  if [ "$code" = "$expect" ]; then
    echo "✅ $code $label"
    PASS=$((PASS+1))
  else
    echo "❌ $code $label (expected $expect)"
    FAIL=$((FAIL+1))
  fi
}

echo "═══════════════════════════════════════"
echo " Dashboard Pages ($DASH_URL)"
echo "═══════════════════════════════════════"

check "GET /"             "$DASH_URL/"
check "GET /home"         "$DASH_URL/home"
check "GET /cockpit"      "$DASH_URL/cockpit"
check "GET /positions"    "$DASH_URL/positions"
check "GET /signals"      "$DASH_URL/signals"
check "GET /conviction"   "$DASH_URL/conviction"
check "GET /forecasts"    "$DASH_URL/forecasts"
check "GET /social"       "$DASH_URL/social"
check "GET /artifacts"    "$DASH_URL/artifacts"
check "GET /performance"  "$DASH_URL/performance"
check "GET /system"       "$DASH_URL/system"
check "GET /settings"     "$DASH_URL/settings"
check "GET /config"       "$DASH_URL/config"
check "GET /treasury"     "$DASH_URL/treasury"

echo ""
echo "═══════════════════════════════════════"
echo " Dashboard HTMX Partials ($DASH_URL)"
echo "═══════════════════════════════════════"

check "GET /partials/kill-dot"              "$DASH_URL/partials/kill-dot"
check "GET /partials/regime-pill"           "$DASH_URL/partials/regime-pill"
check "GET /partials/regime-banner"         "$DASH_URL/partials/regime-banner"
check "GET /partials/positions"             "$DASH_URL/partials/positions"
check "GET /partials/vitals-bar"            "$DASH_URL/partials/vitals-bar"
check "GET /partials/signal-feed"           "$DASH_URL/partials/signal-feed"
check "GET /partials/system-status"         "$DASH_URL/partials/system-status"
check "GET /partials/producers"             "$DASH_URL/partials/producers"
check "GET /partials/kill-switch"           "$DASH_URL/partials/kill-switch"
check "GET /partials/sentiment-map"         "$DASH_URL/partials/sentiment-map"
check "GET /partials/social-alerts"         "$DASH_URL/partials/social-alerts"
check "GET /partials/curator-feed"          "$DASH_URL/partials/curator-feed"
check "GET /partials/karma-intents"         "$DASH_URL/partials/karma-intents"
check "GET /partials/signal-history"        "$DASH_URL/partials/signal-history"
check "GET /partials/forecasts-table"       "$DASH_URL/partials/forecasts-table"
check "GET /partials/discretionary-signals" "$DASH_URL/partials/discretionary-signals"
check "GET /partials/cockpit-content"       "$DASH_URL/partials/cockpit-content"
check "GET /partials/conviction"            "$DASH_URL/partials/conviction"
check "GET /partials/conviction-history"    "$DASH_URL/partials/conviction-history"
check "GET /partials/social-status"         "$DASH_URL/partials/social-status"
check "GET /partials/social-watchlist"      "$DASH_URL/partials/social-watchlist"
check "GET /partials/social-sources"        "$DASH_URL/partials/social-sources"

echo ""
echo "═══════════════════════════════════════"
echo " Dashboard API endpoints ($DASH_URL)"
echo "═══════════════════════════════════════"

check "GET /api/market-ticker"      "$DASH_URL/api/market-ticker"
check "GET /api/dashboard/version"  "$DASH_URL/api/dashboard/version"

echo ""
echo "═══════════════════════════════════════"
echo " API Routes ($API_URL)"
echo "═══════════════════════════════════════"

check "GET /api/v1/health"                    "$API_URL/api/v1/health"
check "GET /api/v1/metrics"                   "$API_URL/api/v1/metrics"
check "GET /api/v1/signals"                   "$API_URL/api/v1/signals"
check "GET /api/v1/positions"                 "$API_URL/api/v1/positions"
check "GET /api/v1/producers/"                "$API_URL/api/v1/producers/"
check "GET /api/v1/producers/status"          "$API_URL/api/v1/producers/status"
check "GET /api/v1/producers/capabilities"    "$API_URL/api/v1/producers/capabilities"
check "GET /api/v1/contributors/"             "$API_URL/api/v1/contributors/"
check "GET /api/v1/contributors/leaderboard"  "$API_URL/api/v1/contributors/leaderboard"
check "GET /api/v1/contributors/attestations" "$API_URL/api/v1/contributors/attestations"
check "GET /api/v1/brain/status"              "$API_URL/api/v1/brain/status"
check "GET /api/v1/kill-switch/status"        "$API_URL/api/v1/kill-switch/status"
check "GET /api/v1/regime"                    "$API_URL/api/v1/regime"
check "GET /api/v1/config"                    "$API_URL/api/v1/config"
check "GET /api/v1/treasury"                  "$API_URL/api/v1/treasury"
check "GET /api/v1/karma/intents"             "$API_URL/api/v1/karma/intents"
check "GET /api/v1/karma/receipts"            "$API_URL/api/v1/karma/receipts"
check "GET /api/v1/social/status"             "$API_URL/api/v1/social/status"
check "GET /api/v1/social/sentiment"          "$API_URL/api/v1/social/sentiment"
check "GET /api/v1/social/alerts"             "$API_URL/api/v1/social/alerts"
check "GET /api/v1/social/narratives"         "$API_URL/api/v1/social/narratives"
check "GET /api/v1/social/sources"            "$API_URL/api/v1/social/sources"
check "GET /api/v1/social/curator-feed"       "$API_URL/api/v1/social/curator-feed"
check "GET /api/v1/social/watchlist"          "$API_URL/api/v1/social/watchlist"
check "GET /api/v1/artifacts/"                "$API_URL/api/v1/artifacts/"
check "GET /api/v1/cockpit/state"             "$API_URL/api/v1/cockpit/state"
check "GET /api/v1/mcp/status"               "$API_URL/api/v1/mcp/status"
check "GET /api/v1/mcp/producers"            "$API_URL/api/v1/mcp/producers"

echo ""
echo "═══════════════════════════════════════"
echo " Summary"
echo "═══════════════════════════════════════"
echo "Total: $TOTAL | Pass: $PASS | Fail: $FAIL"
[ "$FAIL" -eq 0 ] && echo "🎉 All checks passed!" || echo "⚠️  $FAIL failures detected"
exit "$FAIL"
