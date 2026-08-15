# Candidate verification

Verification performed from the Windows source workstation on 2026-08-15:

- Python compile of all source and tests: PASS.
- Import of gateway, orchestrator, autorouting, model manager and graphics manager with
  POSIX-only modules stubbed: PASS. This proves import wiring, not Linux runtime I/O.
- Community invariant suite: 8 tests PASS.
- Existing autorouting regression: PASS (`local_only`, qualification, affinity batch,
  single P40, Qwen restore, failure abort and compact UI contract).
- Real POSIX `flock` contention test: SKIPPED on Windows; mandatory Linux gate.
- JSON parse of registry example and schema: PASS.
- Draft 2020-12 schema validation of the sanitized registry example: PASS.
- Static scan: no site-specific private IPv4 address, legacy host-specific source path, bundled
  credential value, private key marker or model weight in the candidate.

Not claimed: model inference, systemd lifecycle, real GPU exclusion, graphics generation,
or installation on a clean machine. Those remain integration gates.

Generated `__pycache__` files from this local verification are ignored by `.gitignore`
and must not be promoted into the public repository.
