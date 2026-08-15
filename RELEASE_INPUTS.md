# Release inputs still required

This candidate proves packaging mechanics; it is not yet the final public repo.

- Select the canonical production source for portal, orchestration, model
  lifecycle, graphics, users/queue and MCP. Do not merge multiple dated
  candidates by filename similarity.
- Define supported Linux distributions, NVIDIA driver/CUDA matrix and a tested
  P40 baseline.
- Add versioned database migrations and clean initial data fixtures.
- Add a reverse-proxy/TLS recipe without embedding the live domain or LAN IPs.
- Pin container base images by digest and create reproducible release archives.
- Add complete LGPLv3/GPLv3 texts, copyright ownership, third-party notices,
  SBOM, source-offer compliance review and per-model licensing documentation.
- Add secret scanning, dependency scanning, container scanning and signed
  checksums in CI.
- Add real E2E tests for login, concurrent guest queueing, model switching,
  image generation, structured output, upload/OCR and recovery after restart.
- Decide whether the application license should be LGPL, GPL or AGPL with legal
  review; the current SPDX choice records the requested candidate policy only.

