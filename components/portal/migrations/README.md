<!-- SPDX-FileCopyrightText: 2026 R740 AI Factory contributors -->
<!-- SPDX-License-Identifier: LGPL-3.0-or-later -->

# Database migrations

`0001_initial.sql` is generated deterministically from the idempotent fresh-install
schema used by `portal.init_db()`. Existing installations are upgraded by the
guarded column/table migrations in `init_db`; every data migration records its
name in `schema_migrations`.

The Community-specific migration
`20260815_community_demo_guest_opt_in_v1` creates a minimal demo account only
when `AI_DEMO_GUEST_ENABLED=1` and a local password file is supplied. It never
overwrites an existing account and never stores plaintext credentials.

Before the first stable public release, the compatibility migrations embedded in
`init_db` should be split into numbered SQL/Python migration modules. This is a
documented release gap, not hidden behind the initial schema snapshot.

