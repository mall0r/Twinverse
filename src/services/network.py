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
cleanup() {
    trap - EXIT
    # bwrap blocks SIGTERM during setup, including while waiting on --block-fd.
    [ -z "$namespace" ] || kill -KILL "$namespace" 2>/dev/null || true
    [ -z "$sandbox" ] || kill -KILL "$sandbox" 2>/dev/null || true
    [ -z "$helper" ] || kill "$helper" 2>/dev/null || true
    wait 2>/dev/null || true
    rm -rf -- "$state"
}
trap cleanup EXIT
trap 'exit 143' TERM
trap 'exit 130' INT
mkfifo "$state/start"
exec 4<>"$state/start"
printf 'nameserver 169.254.1.1\n' > "$state/resolv.conf"
# bwrap refuses to mount over a symlink, and /etc/resolv.conf is one on hosts
# that use systemd-resolved (Fedora, Bazzite, Ubuntu), netconfig (openSUSE)
# and others. Mounting over the file it points to replaces it all the same,
# and only inside the mount namespace of the sandbox.
resolv_conf=${TWINVERSE_RESOLV_CONF:-/etc/resolv.conf}
resolv_args=(--ro-bind "$state/resolv.conf" "$resolv_conf")
if [ -L "$resolv_conf" ]; then
    resolv_target=$(readlink -f -- "$resolv_conf" 2>/dev/null || true)
    if [ -n "$resolv_target" ] && [ -f "$resolv_target" ]; then
        resolv_args=(--ro-bind "$state/resolv.conf" "$resolv_target")
    else
        # A dangling link cannot be mounted over at all. The instance still
        # starts, with the DNS configuration of the host.
        echo "Twinverse: $resolv_conf points to a missing file; keeping the host DNS configuration" >&2
        resolv_args=()
    fi
fi
: > "$state/info"
bwrap "${options[@]}" --unshare-user --unshare-net \
    ${resolv_args[@]+"${resolv_args[@]}"} \
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
# pasta normally watches the directory of --netns to quit with the namespace,
# but the SELinux policy of passt (Fedora, Bazzite) denies it access to
# /proc/PID/ns of an unconfined process, and pasta exits at once. The cleanup
# above and the process group of the instance already stop it.
pasta --foreground --config-net --no-netns-quit --pid "$state/pasta.pid" \
    --userns "/proc/$namespace/ns/user" --netns "/proc/$namespace/ns/net" \
    --dns-forward 169.254.1.1 -t auto -u auto -T none -U none 4>&- &
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
wait -n "$sandbox" "$helper"
"""


def network_command(command: list[str]) -> list[str]:
    """Attach pasta to one bwrap, retaining its arguments and application."""
    return ["bash", "-c", NETWORK_SETUP, "twinverse-network", *command]
