#!/usr/bin/env bash
# Provision an Amazon Linux 2023 EC2 instance to run SunToday.
# Usage: sudo [NFS_EXPORT=server:/path] ./tools/setup_ec2.sh
# Safe to re-run.
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
    echo "Run with sudo: sudo $0" >&2
    exit 1
fi

dnf install -y docker nfs-utils git
# Enable containerd too; docker.service alone did not survive update reboots.
systemctl enable --now docker.service containerd.service
systemctl is-enabled docker containerd

# Let the invoking user run docker without sudo (takes effect on next login).
DOCKER_USER="${SUDO_USER:-ec2-user}"
usermod -aG docker "$DOCKER_USER"

# AL2023's docker package ships no buildx/compose CLI plugins. Keep these
# versions and SHA-256 digests pinned; update both from the upstream releases.
PLUGIN_DIR=/usr/libexec/docker/cli-plugins
mkdir -p "$PLUGIN_DIR"
BUILDX_VERSION=v0.36.1
BUILDX_SHA256=48af8a397ebd60178778bf63611dbcebe5f5e7a9be90eb9147b24b9587455778
COMPOSE_VERSION=v5.4.0
COMPOSE_SHA256=837fd1d35bf6a494f41b5b5988269a7be79de337cf1a1a6ff0e45ab51bb4e9be

if [ "$(uname -m)" != "x86_64" ]; then
    echo "Unsupported architecture: $(uname -m); this host must be x86_64" >&2
    exit 1
fi

install_plugin() {
    local repo="$1" version="$2" asset="$3" destination="$4" checksum="$5" download
    download="${destination}.download"
    curl -fsSL -o "$download" "https://github.com/docker/${repo}/releases/download/${version}/${asset}"
    printf '%s  %s\n' "$checksum" "$download" | sha256sum -c -
    install -m 0755 "$download" "$destination"
    rm -f "$download"
}

install_plugin buildx "$BUILDX_VERSION" "buildx-${BUILDX_VERSION}.linux-amd64" \
    "$PLUGIN_DIR/docker-buildx" "$BUILDX_SHA256"
install_plugin compose "$COMPOSE_VERSION" "docker-compose-linux-x86_64" \
    "$PLUGIN_DIR/docker-compose" "$COMPOSE_SHA256"
docker buildx version
docker compose version

# Mount the NFS image share now and at every boot.
NFS_EXPORT="${NFS_EXPORT:-nfs.aws.lmsal.com:/mnt/SunInTime}"
if ! grep -q '/opt/SunInTime' /etc/fstab; then
    echo "$NFS_EXPORT /opt/SunInTime nfs defaults,_netdev 0 0" >> /etc/fstab
fi
mkdir -p /opt/SunInTime
mount -a
mountpoint /opt/SunInTime

# Keep NFS writable for containers if SELinux enforcing mode is ever enabled.
setsebool -P virt_use_nfs 1 \
    || echo "warning: setsebool failed (SELinux disabled?); continuing" >&2

cat <<EOF

Done. Next steps, as ${DOCKER_USER}:
  1. Log out and back in (or run 'newgrp docker') to pick up the docker group.
  2. In the SunToday checkout: cp production.env .env, then fill in the AWS
     credentials and set HOST_UID/HOST_GID to a uid/gid that can write to
     /opt/SunInTime ('id -u' / 'id -g'; the default 500 owns the legacy dirs).
  3. docker compose up -d --build
EOF
