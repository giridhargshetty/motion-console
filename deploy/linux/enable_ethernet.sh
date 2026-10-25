#!/usr/bin/env bash
# Turn on DHCP (IPv4 + IPv6) for every wired port. Needed when Ubuntu was installed without a
# network: the installer then leaves the ethernet port without IPv4. Run with sudo.
# Each port is named explicitly so this file merges with (and overrides) the installer's entry
# for the same port; netplan merges same-named entries across files, later files winning.
set -euo pipefail
FILE=/etc/netplan/60-motion-console-ethernet.yaml
{
    echo "network:"
    echo "  version: 2"
    echo "  ethernets:"
    for dev in /sys/class/net/en*; do
        [ -e "$dev/device" ] || continue          # real hardware only
        name="$(basename "$dev")"
        echo "    $name:"
        echo "      dhcp4: true"
        echo "      dhcp6: true"
        echo "      optional: true"                # don't hold boot when the cable is out
    done
} > "$FILE"
chmod 600 "$FILE"
cat "$FILE"
netplan apply
for i in $(seq 1 20); do
    ip -4 -br a | grep -q "^en.*[0-9]\.[0-9]" && break
    sleep 1
done
ip -br a
