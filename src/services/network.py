"""Host-side setup for the existing bwrap's optional rootless network."""

# Run through the existing host launch, so Flatpak needs neither another portal
# call nor a host Python installation. bwrap reports its namespace PID before
# --block-fd releases the application; pasta writes its PID after network setup.
NETWORK_SETUP = r"""
set -eu
shift # bwrap is already checked by the launcher
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
pasta --foreground --config-net --pid "$state/pasta.pid" \
    --userns "/proc/$namespace/ns/user" --netns "/proc/$namespace/ns/net" \
    --dns-forward 169.254.1.1 -t auto -u auto -T none -U none &
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


def network_command(command: list[str]) -> list[str]:
    """Attach pasta to one bwrap, retaining its arguments and application."""
    return ["bash", "-c", NETWORK_SETUP, "twinverse-network", *command]
