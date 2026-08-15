<!-- SPDX-FileCopyrightText: 2026 R740 AI Factory contributors -->
<!-- SPDX-License-Identifier: LGPL-3.0-or-later -->

# Open gaps

The candidate preserves the production portal behavior but is not yet a public
release artifact.

1. **Dependency lock:** direct versions are pinned, but a platform-aware,
   hash-complete transitive lock and SBOM still have to be generated from a clean
   build environment.
2. **Migration framework:** `0001_initial.sql` is reproducible and compatibility
   upgrades are guarded, but the embedded legacy upgrades should become numbered
   migration modules before 1.0.
3. **FastAPI lifespan:** startup/shutdown still use the production `on_event`
   contract and raise deprecation warnings; migrate only with a dedicated
   lifecycle regression because background FIFO/retention tasks are vital.
4. **Integration:** core, parser, tools, sandbox, graphics and MCP are intentionally
   absent by default. Clean-install contract tests for each external service are
   still required.
5. **Copyright:** SPDX treatment is staged, but contributor/copyright ownership
   must be confirmed before the first public commit.
6. **Packaging:** build wheel/sdist, unpack them, rescan for secrets and verify that
   all HTML/migrations are present. This staging has not been merged into the
   Community repository.
7. **Live equivalence:** source ancestry is proven by hash, and local contracts
   pass; no claim is made that this sanitized candidate was deployed to CT120.

