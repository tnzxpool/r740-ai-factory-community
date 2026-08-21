<!-- SPDX-FileCopyrightText: 2026 R740 AI Factory contributors -->
<!-- SPDX-License-Identifier: LGPL-3.0-or-later -->

# Optional service portability

The repository includes sanitized source, templates, notices, SPDX metadata and
SBOM generation for the optional services. They are not enabled by the default
installer because their host requirements differ.

## Parser

Requires Java 17, Tika 3.3.2, Tesseract 5.3 and selected language data. The Tika
JAR is downloaded with a pinned SHA-256; it is not redistributed.

## Read-only tools

Requires a target-specific SearXNG environment. Keep the broker behind the portal
and preserve the SSRF allowlist and firewall boundary.

## Sandbox

Requires a dedicated Linux VM with rootless Podman, project quotas, uidmap,
slirp4netns and fuse-overlayfs. Do not install it on a shared general-purpose host.

## Local MCP

The packaged client uses Windows DPAPI. Pairing/revocation must be tested against
the target portal. macOS Keychain and Linux Secret Service are roadmap items.

## Core and graphics

The service templates are included. GPU lifecycle uses systemd, POSIX flock and
NVIDIA telemetry. The supplied P40 profile is a reproducible target, not a claim
that unrelated hardware is qualified. Model weights remain external and retain
their own licenses.
