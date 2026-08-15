-- SPDX-FileCopyrightText: 2026 R740 AI Factory contributors
-- SPDX-License-Identifier: LGPL-3.0-or-later
-- Generated from src/r740_portal/portal.py; idempotent fresh-install schema.
PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1,
                must_change INTEGER NOT NULL DEFAULT 0,
                created_at INTEGER NOT NULL,
                daily_prompt_limit INTEGER CHECK(
                    daily_prompt_limit IS NULL OR daily_prompt_limit IN (5,10,20)
                )
            );
            CREATE TABLE IF NOT EXISTS sessions (
                token_hash TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                csrf_token TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                last_seen INTEGER NOT NULL,
                expires_at INTEGER NOT NULL,
                bound_ip TEXT
            );
            CREATE TABLE IF NOT EXISTS user_capabilities (
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                capability TEXT NOT NULL,
                enabled INTEGER NOT NULL CHECK(enabled IN (0,1)),
                updated_at INTEGER NOT NULL,
                updated_by INTEGER,
                PRIMARY KEY(user_id,capability)
            );
            CREATE TABLE IF NOT EXISTS user_models (
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                model_id TEXT NOT NULL,
                enabled INTEGER NOT NULL CHECK(enabled IN (0,1)),
                updated_at INTEGER NOT NULL,
                updated_by INTEGER,
                PRIMARY KEY(user_id,model_id)
            );
            CREATE TABLE IF NOT EXISTS schema_migrations (
                name TEXT PRIMARY KEY,
                applied_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS daily_prompt_usage (
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                usage_day TEXT NOT NULL,
                quota_subject TEXT NOT NULL,
                used INTEGER NOT NULL DEFAULT 0 CHECK(used >= 0),
                updated_at INTEGER NOT NULL,
                PRIMARY KEY(user_id,usage_day,quota_subject)
            );
            CREATE TABLE IF NOT EXISTS graphics_requests (
                local_id TEXT PRIMARY KEY,
                job_id TEXT UNIQUE,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                username TEXT NOT NULL,
                source_ip TEXT NOT NULL,
                owner TEXT NOT NULL,
                usage_day TEXT NOT NULL,
                quota_subject TEXT NOT NULL,
                reserved INTEGER NOT NULL CHECK(reserved IN (0,1)),
                state TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                finalized_at INTEGER
            );
            CREATE TABLE IF NOT EXISTS inference_lock (
                slot INTEGER PRIMARY KEY CHECK(slot=1),
                token TEXT NOT NULL UNIQUE,
                kind TEXT NOT NULL CHECK(kind IN ('chat','vision','graphics','maintenance')),
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                username TEXT NOT NULL,
                request_id TEXT NOT NULL,
                acquired_at INTEGER NOT NULL,
                heartbeat_at INTEGER NOT NULL,
                expires_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS inference_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                request_id TEXT NOT NULL UNIQUE,
                owner_key TEXT NOT NULL,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                username TEXT NOT NULL,
                kind TEXT NOT NULL CHECK(kind IN ('chat','vision','graphics','maintenance')),
                state TEXT NOT NULL CHECK(state IN ('waiting','active','finished','cancelled')),
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                waiter_expires_at INTEGER NOT NULL,
                inference_token TEXT,
                finished_reason TEXT
            );
            CREATE TABLE IF NOT EXISTS features (
                name TEXT PRIMARY KEY,
                enabled INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                updated_by INTEGER
            );
            CREATE TABLE IF NOT EXISTS audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at INTEGER NOT NULL,
                user_id INTEGER,
                username TEXT,
                source_ip TEXT,
                event TEXT NOT NULL,
                detail TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at INTEGER NOT NULL,
                request_id TEXT NOT NULL UNIQUE,
                user_id INTEGER NOT NULL REFERENCES users(id),
                username TEXT NOT NULL,
                source_ip TEXT,
                prompt TEXT NOT NULL,
                response TEXT NOT NULL,
                model TEXT NOT NULL,
                metrics_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                mime TEXT NOT NULL,
                size_bytes INTEGER NOT NULL,
                chunk_count INTEGER NOT NULL,
                security_status TEXT NOT NULL DEFAULT 'clean',
                security_score INTEGER NOT NULL DEFAULT 0,
                security_reasons TEXT NOT NULL DEFAULT '[]',
                created_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS document_chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                position INTEGER NOT NULL,
                content TEXT NOT NULL,
                embedding_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS local_mcp_pairing_codes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code_hash TEXT NOT NULL UNIQUE,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                device_name TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                expires_at INTEGER NOT NULL,
                consumed_at INTEGER,
                created_by INTEGER NOT NULL REFERENCES users(id)
            );
            CREATE TABLE IF NOT EXISTS local_mcp_devices (
                device_id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                device_name TEXT NOT NULL,
                public_key TEXT NOT NULL UNIQUE,
                token_hash TEXT NOT NULL UNIQUE,
                schema_hash TEXT,
                tool_names_json TEXT NOT NULL DEFAULT '[]',
                created_at INTEGER NOT NULL,
                last_seen INTEGER,
                revoked_at INTEGER,
                revoked_by INTEGER REFERENCES users(id)
            );
            CREATE INDEX IF NOT EXISTS idx_chunks_document ON document_chunks(document_id,position);
            CREATE INDEX IF NOT EXISTS idx_user_capabilities_user ON user_capabilities(user_id);
            CREATE INDEX IF NOT EXISTS idx_user_models_user ON user_models(user_id);
            CREATE INDEX IF NOT EXISTS idx_daily_prompt_usage_day ON daily_prompt_usage(usage_day,user_id);
            CREATE INDEX IF NOT EXISTS idx_sessions_presence
                ON sessions(last_seen,expires_at,user_id,bound_ip);
            CREATE INDEX IF NOT EXISTS idx_graphics_requests_state ON graphics_requests(finalized_at,state,updated_at);
            CREATE INDEX IF NOT EXISTS idx_inference_queue_fifo ON inference_queue(state,created_at,id);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_inference_queue_one_owner
                ON inference_queue(owner_key) WHERE state IN ('waiting','active');
            CREATE INDEX IF NOT EXISTS idx_local_mcp_pair_user ON local_mcp_pairing_codes(user_id,expires_at);
            CREATE INDEX IF NOT EXISTS idx_local_mcp_device_user ON local_mcp_devices(user_id,revoked_at);
