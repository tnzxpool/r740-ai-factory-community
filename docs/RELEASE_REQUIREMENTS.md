# Release requirements

The first public tag requires all of the following:

- authoritative production sources imported through a file-level provenance
  manifest and sanitized into portable configuration;
- no production identity, credential, database, model weight, log or backup;
- clean CPU install and UI smoke test;
- separate NVIDIA/P40 canary with unsupported hardware failing closed;
- pinned dependencies, third-party notices and SPDX/CycloneDX SBOMs;
- full secret, license, vulnerability and artifact-content scans;
- versioned database migrations, upgrade, backup and uninstall documentation;
- product E2E for authentication, queueing, model switching, graphics, OCR,
  structured output and restart recovery.

The current repository is an installable packaging baseline, not yet the full
production feature set. `RELEASE_INPUTS.md` tracks the remaining integration.

