#!/usr/bin/env bash
# Provision an Amazon Linux 2023 EC2 instance to run SunToday.
# Usage: sudo ./tools/setup_ec2.sh
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

# AL2023's docker package ships no buildx/compose CLI plugins; fetch them.
PLUGIN_DIR=/usr/libexec/docker/cli-plugins
mkdir -p "$PLUGIN_DIR"

# buildx release assets are named linux-amd64; the target t2.medium is x86_64.
BUILDX_VERSION=$(curl -fsSL https://api.github.com/repos/docker/buildx/releases/latest \
    | grep -oP '"tag_name": "\K[^"]+')
curl -fsSL -o "$PLUGIN_DIR/docker-buildx" \
    "https://github.com/docker/buildx/releases/download/${BUILDX_VERSION}/buildx-${BUILDX_VERSION}.linux-amd64"
curl -fsSL -o "$PLUGIN_DIR/docker-compose" \
    "https://github.com/docker/compose/releases/latest/download/docker-compose-linux-$(uname -m)"
chmod +x "$PLUGIN_DIR/docker-buildx" "$PLUGIN_DIR/docker-compose"
docker buildx version
docker compose version

# Mount the NFS image share now and at every boot.
if ! grep -q '/opt/SunInTime' /etc/fstab; then
    echo 'nfs.aws.lmsal.com:/mnt/SunInTime /opt/SunInTime nfs defaults,_netdev 0 0' >> /etc/fstab
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
