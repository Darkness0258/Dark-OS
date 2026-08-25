#!/usr/bin/env bash
# Destructive live-guest network exercise for ensure-network.service.
#
# Run this only in the disposable VMware live ISO. It intentionally stops
# NetworkManager, flushes the wired interface, and drops its carrier state.
# The caller should start it as a transient systemd unit so it survives the
# resulting SSH disconnect and can copy this log back afterward.

set -Eeuo pipefail

readonly LOG_PATH=/var/tmp/darkos-ensure-network-runtime.log
readonly STATUS_PATH=/var/tmp/darkos-ensure-network-runtime.status

rm -f -- "${STATUS_PATH}"
exec > >(tee "${LOG_PATH}") 2>&1

finish() {
    local status=$?
    if (( status == 0 )); then
        printf 'RESULT=PASS\nEXIT_CODE=0\n' > "${STATUS_PATH}"
    else
        printf 'RESULT=FAIL\nEXIT_CODE=%s\n' "${status}" > "${STATUS_PATH}"
    fi
}
trap finish EXIT

fail() {
    printf 'FAIL: %s\n' "$*" >&2
    exit 1
}

(( EUID == 0 )) || fail 'runtime exercise must run as root'
[[ -e /run/archiso ]] || fail 'runtime exercise is restricted to the disposable live ISO'

iface="$(
    ip -o link show \
        | awk -F': ' '{print $2}' \
        | sed 's/@.*$//' \
        | grep -vE '^(lo|wlan|wwan)' \
        | head -n1
)"
[[ -n "${iface}" ]] || fail 'no wired interface was found'

printf 'UTC_START=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
printf 'INTERFACE=%s\n' "${iface}"
printf '%s\n' '=== INITIAL UNIT TIMESTAMPS ==='
systemctl show ensure-network.service NetworkManager.service \
    -p Id -p ActiveState -p SubState -p Result \
    -p InactiveEnterTimestamp -p ActiveEnterTimestamp \
    -p ExecMainStartTimestamp -p ExecMainExitTimestamp
printf '%s\n' '=== INITIAL ADDRESS AND ROUTES ==='
ip -4 addr show dev "${iface}"
ip -4 route show

start_marker="$(date -u '+%Y-%m-%d %H:%M:%S')"
systemctl stop NetworkManager.service
printf '%s\n' '=== NETWORKMANAGER STOPPED ==='
systemctl is-active NetworkManager.service || true

ip address flush dev "${iface}"
ip link set dev "${iface}" down
if ip -o -4 address show dev "${iface}" scope global | grep -q .; then
    fail 'wired interface retained a global IPv4 address after flush'
fi
printf '%s\n' '=== INTERFACE FLUSHED AND DOWN ==='
ip link show dev "${iface}"
ip -4 addr show dev "${iface}"
ip -4 route show

systemctl reset-failed ensure-network.service
printf '%s\n' '=== PLAIN MANUAL START ==='
systemctl start ensure-network.service
# A successful Type=oneshot without RemainAfterExit returns to inactive/dead,
# so `systemctl status` itself exits 3. Preserve its raw output and assert the
# service result/status fields explicitly instead.
systemctl status ensure-network.service --no-pager --full || true
[[ "$(systemctl show ensure-network.service -p Result --value)" == success ]] \
    || fail 'manual ensure-network run did not report Result=success'
[[ "$(systemctl show ensure-network.service -p ExecMainStatus --value)" == 0 ]] \
    || fail 'manual ensure-network run did not exit with status zero'
printf '%s\n' '=== FALLBACK JOURNAL ==='
journalctl -u ensure-network.service --since "${start_marker}" --no-pager -o short-iso-precise

fallback_addresses="$(ip -o -4 address show dev "${iface}" scope global | wc -l)"
fallback_routes="$(ip -4 route show default dev "${iface}" | wc -l)"
printf 'FALLBACK_GLOBAL_IPV4_COUNT=%s\n' "${fallback_addresses}"
printf 'FALLBACK_DEFAULT_ROUTE_COUNT=%s\n' "${fallback_routes}"
(( fallback_addresses == 1 )) || fail 'fallback did not leave exactly one global IPv4 address'
(( fallback_routes == 1 )) || fail 'fallback did not leave exactly one default route'

printf '%s\n' '=== FALLBACK ADDRESS AND ROUTES ==='
ip -4 addr show dev "${iface}"
ip -4 route show
if pgrep -x dhcpcd >/dev/null; then
    pgrep -a -x dhcpcd
    fail 'one-shot fallback left a dhcpcd process running'
fi
printf '%s\n' 'DHCPCD_PROCESS_COUNT=0'

ping -c 3 -W 3 1.1.1.1
printf '%s\n' 'IP_EGRESS_PING=PASS'
if ping -c 2 -W 3 archlinux.org; then
    printf '%s\n' 'DNS_EGRESS_PING=PASS'
else
    printf '%s\n' 'DNS_EGRESS_PING=UNAVAILABLE'
fi

restart_marker="$(date -u '+%Y-%m-%d %H:%M:%S')"
systemctl start NetworkManager.service
for _ in {1..30}; do
    if systemctl is-active --quiet NetworkManager.service \
        && nmcli -t -f GENERAL.STATE device show "${iface}" 2>/dev/null \
            | grep -q ':100 (connected)$'; then
        break
    fi
    sleep 1
done
systemctl is-active --quiet NetworkManager.service \
    || fail 'NetworkManager did not return to active state'
sleep 10

final_addresses="$(ip -o -4 address show dev "${iface}" scope global | wc -l)"
final_routes="$(ip -4 route show default dev "${iface}" | wc -l)"
printf 'FINAL_GLOBAL_IPV4_COUNT=%s\n' "${final_addresses}"
printf 'FINAL_DEFAULT_ROUTE_COUNT=%s\n' "${final_routes}"
(( final_addresses == 1 )) || fail 'NetworkManager left duplicate or missing global IPv4 addresses'
(( final_routes == 1 )) || fail 'NetworkManager left duplicate or missing default routes'

printf '%s\n' '=== NETWORKMANAGER RESTART JOURNAL ==='
nm_journal="$(journalctl -u NetworkManager.service --since "${restart_marker}" --no-pager -o short-iso-precise)"
printf '%s\n' "${nm_journal}"
if grep -Eiq 'duplicate address|address conflict|already configured|ip-config.*failed' <<< "${nm_journal}"; then
    fail 'NetworkManager reported an address conflict after fallback takeover'
fi
printf '%s\n' 'NETWORKMANAGER_CONFLICT_SCAN=PASS'

printf '%s\n' '=== FINAL ADDRESS AND ROUTES ==='
ip -4 addr show dev "${iface}"
ip -4 route show
ping -c 3 -W 3 1.1.1.1
printf '%s\n' 'FINAL_IP_EGRESS_PING=PASS'
printf 'UTC_END=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
