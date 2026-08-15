import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from ai_tools.app import (
    Actor,
    Broker,
    SafeFetcher,
    Settings,
    Store,
    ToolError,
    create_app,
    safe_source_url,
    validate_url,
)


PUBLIC_DNS = lambda host, port: ["93.184.216.34", "2606:2800:220:1:248:1893:25c8:1946"]


class FakeSearch:
    def __init__(self, fail=False):
        self.fail = fail
        self.calls = []

    def search(self, query, limit):
        self.calls.append((query, limit))
        if self.fail:
            raise ToolError("search_upstream_failed", "down", 502)
        return [{"title": "Example", "url": "https://example.com/a", "snippet": "data", "trust": "untrusted_external_content"}][:limit]


class FakeFetcher:
    def __init__(self, fail=False):
        self.fail = fail

    def fetch(self, url):
        if self.fail:
            raise ToolError("dns_failed", "failed", 502)
        return {"url": url, "text": "external", "bytes": 8, "trust": "untrusted_external_content"}


class UrlPolicyTests(unittest.TestCase):
    def test_public_url_is_canonicalized_and_pinned(self):
        target = validate_url("https://Example.COM/a b?q=1", PUBLIC_DNS)
        self.assertEqual(target.hostname, "example.com")
        self.assertEqual(target.target, "/a%20b?q=1")
        self.assertEqual(len(target.ips), 2)

    def test_ip_literals_are_forbidden(self):
        for url in ("http://127.0.0.1/", "http://[::1]/", "http://169.254.169.254/latest"):
            with self.subTest(url=url), self.assertRaisesRegex(ToolError, "IP literal"):
                validate_url(url, PUBLIC_DNS)

    def test_any_private_dns_answer_fails_closed(self):
        for answers in (["10.0.0.1"], ["93.184.216.34", "172.16.0.10"], ["fe80::1"]):
            with self.subTest(answers=answers), self.assertRaisesRegex(ToolError, "non-public"):
                validate_url("https://example.com/", lambda h, p, a=answers: a)

    def test_dns_failure_empty_answer_and_local_name_are_blocked(self):
        with self.assertRaises(ToolError):
            validate_url("https://example.com", lambda h, p: [])
        for url in ("http://localhost/", "http://printer.local/", "http://intranet/"):
            with self.subTest(url=url), self.assertRaises(ToolError):
                validate_url(url, PUBLIC_DNS)

    def test_credentials_controls_and_non_web_ports_are_blocked(self):
        for url in (
            "https://user:pass@example.com/",
            "https://example.com:22/",
            "file:///etc/passwd",
            "https://example.com/\r\nX-Evil: yes",
        ):
            with self.subTest(url=url), self.assertRaises(ToolError):
                validate_url(url, PUBLIC_DNS)

    def test_source_url_sanitizer(self):
        self.assertTrue(safe_source_url("https://example.com/story"))
        self.assertFalse(safe_source_url("http://127.0.0.1/x"))
        self.assertFalse(safe_source_url("file:///etc/passwd"))
        self.assertFalse(safe_source_url("https://example.com:notaport/x"))
        self.assertFalse(safe_source_url("https://printer.local/x"))


class FetchTests(unittest.TestCase):
    def test_html_is_text_only_and_scripts_are_removed(self):
        calls = []

        def requester(target, timeout, limit):
            calls.append(target.ips)
            return 200, {"content-type": "text/html; charset=utf-8"}, b"<h1>Hello</h1><script>steal()</script><p>World</p>"

        result = SafeFetcher(resolver=PUBLIC_DNS, requester=requester).fetch("https://example.com/")
        self.assertIn("93.184.216.34", calls[0])
        self.assertIn("Hello", result["text"])
        self.assertNotIn("steal", result["text"])
        self.assertEqual(result["trust"], "untrusted_external_content")

    def test_each_redirect_is_resolved_and_private_target_is_blocked(self):
        resolved = []

        def resolver(host, port):
            resolved.append(host)
            return ["10.0.0.4"] if host == "private.example" else ["93.184.216.34"]

        def requester(target, timeout, limit):
            return 302, {"location": "https://private.example/secret"}, b""

        with self.assertRaisesRegex(ToolError, "non-public"):
            SafeFetcher(resolver=resolver, requester=requester).fetch("https://example.com/")
        self.assertEqual(resolved, ["example.com", "private.example"])

    def test_redirect_limit(self):
        def requester(target, timeout, limit):
            return 302, {"location": "/again"}, b""

        with self.assertRaisesRegex(ToolError, "Redirect limit"):
            SafeFetcher(resolver=PUBLIC_DNS, requester=requester, max_redirects=3).fetch("https://example.com/")

    def test_binary_content_is_rejected(self):
        def requester(target, timeout, limit):
            return 200, {"content-type": "image/png"}, b"png"

        with self.assertRaisesRegex(ToolError, "text document"):
            SafeFetcher(resolver=PUBLIC_DNS, requester=requester).fetch("https://example.com/a.png")

    def test_mock_transport_cannot_bypass_size_cap(self):
        def requester(target, timeout, limit):
            self.assertEqual(timeout, 2.5)
            self.assertEqual(limit, 8)
            return 200, {"content-type": "text/plain"}, b"123456789"

        with self.assertRaisesRegex(ToolError, "size limit"):
            SafeFetcher(resolver=PUBLIC_DNS, requester=requester, timeout=2.5, max_bytes=8).fetch(
                "https://example.com/large"
            )


class BrokerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = str(Path(self.tmp.name) / "tools.db")
        self.settings = Settings("x" * 40, self.db, default_daily_limit=2, max_search_results=8)
        self.store = Store(self.db)
        self.actor = Actor("user-1", "user", frozenset({"web_search", "web_fetch"}), 2)

    def tearDown(self):
        self.tmp.cleanup()

    def test_quota_is_transactional_and_audit_hides_input(self):
        broker = Broker(self.settings, self.store, FakeSearch(), FakeFetcher())
        one = broker.call(self.actor, "web_search", {"query": "private words", "max_results": 5})
        two = broker.call(self.actor, "web_fetch", {"url": "https://example.com/private"})
        self.assertEqual(one["quota_remaining"], 1)
        self.assertEqual(two["quota_remaining"], 0)
        with self.assertRaisesRegex(ToolError, "quota"):
            broker.call(self.actor, "web_search", {"query": "third", "max_results": 5})
        con = sqlite3.connect(self.db)
        try:
            rows = con.execute("SELECT input_sha256,status,error_code,response_bytes FROM audit ORDER BY id").fetchall()
            audit_dump = json.dumps(rows)
        finally:
            con.close()
        self.assertNotIn("private words", audit_dump)
        self.assertEqual([row[1] for row in rows], ["ok", "ok", "error"])
        self.assertEqual(rows[-1][2], "quota_exhausted")

    def test_failed_upstream_refunds_quota(self):
        broker = Broker(self.settings, self.store, FakeSearch(fail=True), FakeFetcher())
        with self.assertRaises(ToolError):
            broker.call(self.actor, "web_search", {"query": "x", "max_results": 1})
        con = sqlite3.connect(self.db)
        try:
            used = con.execute("SELECT used FROM daily_usage").fetchone()[0]
        finally:
            con.close()
        self.assertEqual(used, 0)

    def test_capability_is_enforced_before_quota(self):
        broker = Broker(self.settings, self.store, FakeSearch(), FakeFetcher())
        denied = Actor("limited", "tester", frozenset({"web_search"}), 5)
        with self.assertRaisesRegex(ToolError, "not enabled"):
            broker.call(denied, "web_fetch", {"url": "https://example.com"})
        con = sqlite3.connect(self.db)
        try:
            self.assertIsNone(con.execute("SELECT used FROM daily_usage WHERE actor_id='limited'").fetchone())
        finally:
            con.close()


class ApiAndMcpTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.settings = Settings(
            "t" * 40, str(Path(self.tmp.name) / "db.sqlite"), default_daily_limit=4,
            trusted_client_ips=frozenset({"*"}),
        )
        self.app = create_app(
            self.settings,
            search_provider=FakeSearch(),
            fetcher=FakeFetcher(),
        )
        self.client = TestClient(self.app)
        self.headers = {
            "Authorization": "Bearer " + "t" * 40,
            "X-AI-User": "tester-77",
            "X-AI-Role": "tester",
            "X-AI-Capabilities": "web_search",
            "X-AI-Daily-Limit": "4",
        }

    def tearDown(self):
        self.tmp.cleanup()

    def test_health_has_no_upstream_or_secret_detail(self):
        response = self.client.get("/healthz")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("token", response.text.lower())

    def test_auth_and_rest_capability(self):
        self.assertEqual(self.client.post("/v1/tools/web_search", json={"query": "x"}).status_code, 401)
        ok = self.client.post("/v1/tools/web_search", headers=self.headers, json={"query": "x"})
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(ok.json()["trust"], "untrusted_external_content")
        denied = self.client.post(
            "/v1/tools/web_fetch", headers=self.headers, json={"url": "https://example.com"}
        )
        self.assertEqual(denied.status_code, 403)

    def test_mcp_initialize_list_and_call(self):
        initialized = self.client.post(
            "/mcp", headers=self.headers,
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        )
        self.assertEqual(initialized.status_code, 200)
        self.assertEqual(initialized.json()["result"]["protocolVersion"], "2025-06-18")
        listed = self.client.post(
            "/mcp", headers=self.headers,
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        ).json()
        self.assertEqual([tool["name"] for tool in listed["result"]["tools"]], ["web_search"])
        called = self.client.post(
            "/mcp", headers=self.headers,
            json={"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "web_search", "arguments": {"query": "r740"}}},
        ).json()
        self.assertFalse(called["result"]["isError"])
        self.assertEqual(called["result"]["structuredContent"]["tool"], "web_search")

    def test_mcp_notification_and_unknown_method(self):
        note = self.client.post(
            "/mcp", headers=self.headers,
            json={"jsonrpc": "2.0", "method": "notifications/initialized"},
        )
        self.assertEqual(note.status_code, 202)
        unknown = self.client.post(
            "/mcp", headers=self.headers,
            json={"jsonrpc": "2.0", "id": 9, "method": "resources/list"},
        )
        self.assertEqual(unknown.status_code, 404)
        self.assertEqual(unknown.json()["error"]["code"], -32601)
        invalid_params = self.client.post(
            "/mcp", headers=self.headers,
            json={"jsonrpc": "2.0", "id": 10, "method": "tools/call", "params": []},
        )
        self.assertEqual(invalid_params.status_code, 400)
        self.assertEqual(invalid_params.json()["error"]["code"], -32602)

    def test_mcp_rejects_untrusted_browser_origin(self):
        headers = dict(self.headers)
        headers["Origin"] = "https://evil.example"
        response = self.client.post(
            "/mcp", headers=headers,
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "origin_forbidden")

    def test_spoofed_role_does_not_grant_unlisted_capability(self):
        headers = dict(self.headers)
        headers["X-AI-Role"] = "admin"
        headers["X-AI-Capabilities"] = "shell,filesystem_write,web_search"
        listed = self.client.post(
            "/mcp", headers=headers,
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        ).json()
        self.assertEqual([tool["name"] for tool in listed["result"]["tools"]], ["web_search"])


if __name__ == "__main__":
    unittest.main()
