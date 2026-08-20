FROM archlinux:latest

LABEL org.opencontainers.image.title="DarkOS ISO Builder"
LABEL org.opencontainers.image.description="Privileged ArchISO build environment for DarkOS"

WORKDIR /workspace

ENTRYPOINT ["/usr/bin/bash", "/workspace/ci/docker-build-iso.sh"]
