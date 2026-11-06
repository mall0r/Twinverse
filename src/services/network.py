"""Host-side setup for the existing bwrap's optional rootless network."""

from typing import Optional

# Pick a free IPv4 address for the guest from the end of the host's subnet.
# The address has to be in the same subnet as the host, otherwise the guest
# would send the traffic to the gateway instead of reaching a server that runs
# on the host. The blocks keep the instances of one launch apart, because the
# addresses assigned by pasta are not visible to the other instances.
GUEST_ADDRESS_SETUP = r"""
ipv4_to_int() {
    local a b c d
    IFS=. read -r a b c d <<< "$1"
    echo $(( (a << 24) | (b << 16) | (c << 8) | d ))
}
int_to_ipv4() {
    echo "$(( ($1 >> 24) & 255 )).$(( ($1 >> 16) & 255 )).$(( ($1 >> 8) & 255 )).$(( $1 & 255 ))"
}
host_cidr() {
    local iface cidr
    iface=$(ip -4 route show default 2>/dev/null | awk '{for (i = 1; i <= NF; i++) if ($i == "dev") { print $(i + 1); exit }}')
    [ -n "$iface" ] || iface=$(ip -4 -o addr show scope global 2>/dev/null | awk 'NR == 1 { print $2 }')
    [ -n "$iface" ] || return 1
    cidr=$(ip -4 -o addr show dev "$iface" scope global 2>/dev/null | awk 'NR == 1 { print $4 }')
    [ -n "$cidr" ] || return 1
    echo "$iface $cidr"
}
host_prefix() {
    local cidr
    cidr=$(host_cidr) || return 1
    cidr=${cidr#* }
    echo "${cidr#*/}"
}
arp_has_address() {
    local ip=$1 arp_file=${TWINVERSE_ARP_FILE:-/proc/net/arp}
    awk -v ip="$ip" '$1 == ip && $4 != "00:00:00:00:00:00" { found = 1 } END { exit !found }' "$arp_file" 2>/dev/null
}
address_in_use() {
    local ip=$1
    arp_has_address "$ip" && return 0
    # Resolve the address before reading the table, so a host that drops ICMP
    # is still found by the ARP reply it sends. A free address leaves the
    # entry incomplete and is safe to use.
    if command -v ping >/dev/null 2>&1; then
        if command -v timeout >/dev/null 2>&1; then
            timeout 0.7 ping -c 1 -W 1 -q "$ip" >/dev/null 2>&1 || true
        else
            ping -c 1 -W 1 -q "$ip" >/dev/null 2>&1 || true
        fi
    fi
    arp_has_address "$ip"
}
select_guest_address() {
    local index=${1:-0} iface cidr address prefix host_int mask network broadcast block candidate ip offset
    read -r iface cidr <<< "$(host_cidr)" || return 1
    [ -n "$iface" ] && [ -n "$cidr" ] || return 1
    address=${cidr%/*}
    prefix=${cidr#*/}
    case "$prefix" in ''|*[!0-9]*) return 1 ;; esac
    [ "$prefix" -ge 8 ] && [ "$prefix" -le 30 ] || return 1
    host_int=$(ipv4_to_int "$address")
    mask=$(( (0xFFFFFFFF << (32 - prefix)) & 0xFFFFFFFF ))
    network=$(( host_int & mask ))
    broadcast=$(( network | (~mask & 0xFFFFFFFF) ))
    # One block of four addresses per instance, from the top of the subnet.
    block=$(( 2 + index * 4 ))
    for ((offset = 0; offset < 4; offset++)); do
        candidate=$(( broadcast - block - offset ))
        [ "$candidate" -gt "$network" ] || continue
        [ "$candidate" -ne "$host_int" ] || continue
        ip=$(int_to_ipv4 "$candidate")
        address_in_use "$ip" && continue
        echo "$ip/$prefix"
        return 0
    done
    # A block can be crowded on a busy network; fall back to the rest of the
    # top of the subnet. A duplicate is harmless, but a free address is not.
    for ((offset = 2; offset < 2 + 32; offset++)); do
        candidate=$(( broadcast - offset ))
        [ "$candidate" -gt "$network" ] || continue
        [ "$candidate" -ne "$host_int" ] || continue
        ip=$(int_to_ipv4 "$candidate")
        address_in_use "$ip" && continue
        echo "$ip/$prefix"
        return 0
    done
    return 1
}
"""

# Run through the existing host launch, so Flatpak needs neither another portal
# call nor a host Python installation. bwrap reports its namespace PID before
# --block-fd releases the application; pasta writes its PID after network setup.
NETWORK_SETUP = (
    r"""
set -eu
guest_address=${1-}
instance_index=${2-0}
shift 2
shift # bwrap is already checked by the launcher
"""
    + GUEST_ADDRESS_SETUP
    + r"""
options=()
while [ "$1" != -- ]; do
    options+=("$1")
    shift
done
shift
state=$(mktemp -d "${XDG_RUNTIME_DIR:-/tmp}/twinverse-net.XXXXXX")
sandbox=
helper=
namespace=
setup_done=0
cleanup() {
    trap - EXIT
    # bwrap blocks SIGTERM during setup, including while waiting on --block-fd.
    # After the setup the application is left alone, so the group can close
    # in order, with the compositor and the sandbox before the network.
    if [ "$setup_done" -eq 0 ]; then
        [ -z "$namespace" ] || kill -KILL "$namespace" 2>/dev/null || true
        [ -z "$sandbox" ] || kill -KILL "$sandbox" 2>/dev/null || true
    fi
    [ -z "$helper" ] || kill "$helper" 2>/dev/null || true
    wait 2>/dev/null || true
    rm -rf -- "$state"
}
forward_term() {
    # Ask the group to stop, and give it time to close on its own instead
    # of being killed right away.
    [ -z "$sandbox" ] || kill -TERM "$sandbox" 2>/dev/null || true
    for ((i = 0; i < 100; i++)); do
        kill -0 "$sandbox" 2>/dev/null || break
        sleep 0.1
    done
    exit 143
}
trap cleanup EXIT
trap forward_term TERM
trap 'exit 130' INT
mkfifo "$state/start"
exec 4<>"$state/start"
printf 'nameserver 169.254.1.1\n' > "$state/resolv.conf"
: > "$state/info"
bwrap "${options[@]}" --unshare-user --unshare-net \
    --ro-bind "$state/resolv.conf" /etc/resolv.conf \
    --info-fd 3 --block-fd 4 -- "$@" 3>"$state/info" &
sandbox=$!
for ((i=0; i<200; i++)); do
    info=$(<"$state/info")
    if [[ $info =~ \"child-pid\":[[:space:]]*([0-9]+) ]]; then
        namespace=${BASH_REMATCH[1]}
        break
    fi
    kill -0 "$sandbox" 2>/dev/null || { wait "$sandbox"; exit 1; }
    sleep 0.05
done
[ -n "$namespace" ] || { echo 'Twinverse: network namespace setup timed out' >&2; exit 1; }
pasta_address_args=()
if [ -z "$guest_address" ]; then
    guest_address=$(select_guest_address "$instance_index" 2>/dev/null || true)
elif [[ "$guest_address" != */* ]]; then
    prefix=$(host_prefix 2>/dev/null || true)
    guest_address="$guest_address/${prefix:-24}"
fi
if [ -n "$guest_address" ]; then
    pasta_address_args=(-a "$guest_address")
    echo "Twinverse: guest address $guest_address" >&2
else
    echo 'Twinverse: no free guest address; sharing the host address' >&2
fi
pasta --foreground --config-net --pid "$state/pasta.pid" \
    --userns "/proc/$namespace/ns/user" --netns "/proc/$namespace/ns/net" \
    --dns-forward 169.254.1.1 ${pasta_address_args[@]+"${pasta_address_args[@]}"} \
    -t auto -u auto -T none -U none &
helper=$!
for ((i=0; i<200; i++)); do
    [ ! -s "$state/pasta.pid" ] || break
    kill -0 "$helper" 2>/dev/null || { wait "$helper"; exit 1; }
    sleep 0.05
done
[ -s "$state/pasta.pid" ] || { echo 'Twinverse: pasta setup timed out' >&2; exit 1; }
echo 'Twinverse: isolated network enabled (pasta)' >&2
printf '1' >&4
exec 4>&-
setup_done=1
wait -n "$sandbox" "$helper"
"""
)


def network_command(
    command: list[str], guest_address: Optional[str] = None, instance_index: int = 0
) -> list[str]:
    """Attach pasta to one bwrap, retaining its arguments and application."""
    return [
        "bash",
        "-c",
        NETWORK_SETUP,
        "twinverse-network",
        guest_address or "",
        str(max(0, int(instance_index))),
        *command,
    ]
