# Community 0.2 release requirements

The Community 0.2 tag requires all of the following:

- authoritative production sources imported through a file-level provenance
  manifest and sanitized into portable configuration;
- no production identity, credential, database, model weight, log or backup;
- clean CPU install and UI smoke test;
- pinned dependencies, third-party notices and SPDX/CycloneDX SBOMs;
- secret and artifact-content scans for the packaged tree;
- upgrade, backup, rollback and uninstall documentation;
- authenticated control-plane chat E2E against a disposable backend;
- container build and clean bootstrap in CI.

The following are separate qualification gates, not claims of this tag: real
P40 inference with operator-supplied weights; parser/sandbox/graphics E2E;
complete transitive vulnerability scanning for each target distribution; and
the full private multi-service topology. `RELEASE_INPUTS.md` tracks that roadmap.
