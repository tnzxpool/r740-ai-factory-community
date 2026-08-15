<!-- SPDX-FileCopyrightText: 2026 R740 AI Factory contributors -->
<!-- SPDX-License-Identifier: LGPL-3.0-or-later -->

# R740 AI Factory Community portal candidate

Sanitized staging assembled from the hash-identical CT120 portal inventory. It
does not modify or depend on the live server and has not been copied into the
Community repository.

## Preserved behavior

- compact responsive UI and fixed composer;
- separate chat-model and graphics-engine selectors;
- qualified/installed model filtering and red accessible uncensored label;
- explicit graphics apply action and SDXL/RealVis allowlist;
- persistent single-heavy-model FIFO, leases, cancellation and quota refund;
- Guest network binding and hard denial of sandbox/local MCP;
- Admin capability/model management, account deletion and password reset;
- documents, OCR/direct vision, tools, sandbox and MCP adapters;
- CSRF, secure sessions, retention, audit and prompt-injection boundaries.

## Community changes

- production domain, LAN endpoints and host-specific paths have no defaults;
- trusted hosts and Admin CIDR are explicit configuration;
- missing backends are not advertised and calls fail with 503;
- the demo account is absent by default;
- enabling demo mode requires a local password file, stores only Argon2 and never
  publishes the credential through the login page or public-config API;
- the login page contains no embedded username/password pair;
- HTML, Python, SQL, requirements and build metadata carry LGPL SPDX declarations.

## Local smoke test

```text
python -m venv .venv
.venv/bin/pip install -r requirements-test.txt
python -m pytest -q
python tests/secret_scan.py
```

Start only after copying `runtime.env.example` outside the source tree, setting
explicit hosts/Admin CIDR, and generating a one-time setup-token SHA-256:

```text
uvicorn r740_portal.portal:app --app-dir src --host 127.0.0.1 --port 8080
```

With no core URL/key, `/health` remains available while chat/model/graphics calls
fail closed. Do not set demo mode unless the installation owner deliberately
creates and protects the password file.

See `SOURCE_MANIFEST.json` for ancestry and `GAPS.md` for remaining release gates.

