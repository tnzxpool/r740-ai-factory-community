<!-- SPDX-FileCopyrightText: 2026 R740 AI Factory contributors -->
<!-- SPDX-License-Identifier: LGPL-3.0-or-later -->

# Portal limitations and roadmap

The Community portal is packaged and installable. Its default profile is local,
creates no demo credential, and keeps optional services disabled until configured.

Remaining advanced work:

1. replace embedded compatibility upgrades with fully numbered migrations before 1.0;
2. migrate FastAPI `on_event` hooks to lifespan after FIFO and retention regression tests;
3. publish platform-specific transitive locks for every supported Linux target;
4. run clean-machine E2E matrices for parser, tools, sandbox, graphics, and Local-MCP;
5. add macOS/Linux secure-storage adapters to the Windows DPAPI Local-MCP client.

These limitations do not block the local control-plane or portal quickstarts.
