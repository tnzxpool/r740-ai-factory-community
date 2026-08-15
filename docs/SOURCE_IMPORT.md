# Production source import

`SOURCE_PROVENANCE.json` records hashes only. It intentionally contains no live
address, local workspace path, credential or runtime value.

Every production component follows this sequence:

1. verify the input file against the recorded SHA-256;
2. review copyright and third-party provenance;
3. replace addresses, paths and credentials with typed configuration;
4. add SPDX and tests while preserving security behavior;
5. run the package audit and component regression suite;
6. change `import_status` to `integrated` only after a clean-install test.

Raw production exports remain outside this Git repository and must never be
committed. The provenance hash demonstrates the source used for the rewrite
without publishing private deployment configuration.

