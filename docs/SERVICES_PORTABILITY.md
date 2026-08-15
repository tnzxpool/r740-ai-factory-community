# Portability gaps

## Parser

- The Tika JAR is intentionally absent; the pinned downloader needs network.
- Java 17, Tesseract 5.3 and ENG/ITA data must be installed per distribution.
- Only auth/health is portable-tested here; the Office/OCR matrix needs Linux.

## Tools

- SearXNG is pinned to an upstream commit but its Python transitive dependency
  lock must be regenerated reproducibly for each supported distribution.
- Production isolation still requires firewall rules allowing only the portal.
- Existing SSRF unit tests need the locked FastAPI/TestClient environment.

## Sandbox

- Requires a dedicated Linux VM, rootless Podman, project quotas, uidmap,
  slirp4netns and fuse-overlayfs. A general-purpose shared host is not supported.
- The service retains narrowly required privileged capabilities for quota and
  rootless-runner management; host firewall and VM isolation remain mandatory.
- Clean-install, hostile execution and quota exhaustion tests remain Linux gates.

## Local MCP

- Secure storage is Windows DPAPI-specific. macOS Keychain and Linux Secret
  Service adapters do not exist yet.
- Server-side pairing/revocation is outside this candidate and needs E2E testing.
- Dependency hashes currently reflect the authoritative Windows 0.2.1 baseline;
  other platforms need separately generated hash-locked artifacts.

## Release-wide

- Complete LGPL/GPL texts, copyright review, third-party notices and SBOM remain
  release gates. SPDX headers record intended policy, not completed clearance.
- No service should be enabled until templates are rendered, local secrets are
  generated, bind/allowlist values are reviewed and a firewall is active.

