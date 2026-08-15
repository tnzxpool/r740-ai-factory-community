# R740 AI Factory community core candidate

Sanitized source staging derived from the hash-verified CT101 runtime. It is not a
deployment bundle and does not contain model weights, credentials, live state, host
addresses, qualification artefacts or service configuration from the private server.

The default configuration is fail-closed:

- all service URLs are HTTP loopback literals;
- portal, backend and orchestrator credentials default to empty, so authenticated
  routes reject requests until the installer generates independent secrets;
- autorouting execution defaults off and remote routing is forbidden;
- one inference semaphore, one workflow lock and one GPU lock are retained;
- the graphics queue remains a bounded FIFO with per-owner limits;
- models are unavailable until local qualification evidence passes.

Run the candidate tests with `python -m unittest discover -s tests -v`. This staging
still requires portable systemd/model runtime templates before it can be installed.

See `SOURCE-MANIFEST.json` and `NONPORTABLE.md` for ancestry and remaining platform
assumptions.
