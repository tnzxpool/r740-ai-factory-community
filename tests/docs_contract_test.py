#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-3.0-or-later
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    install = (ROOT / "docs/INSTALL.md").read_text(encoding="utf-8")
    html = (ROOT / "src/r740_factory/static/index.html").read_text(encoding="utf-8")
    javascript = (ROOT / "src/r740_factory/static/app.js").read_text(encoding="utf-8")
    for path in ("scripts/bootstrap-compose.sh", "scripts/preflight.sh", "scripts/verify-install.py", "scripts/register-local-model.py", "scripts/package-release.sh"):
        assert path in readme or path in install, path
        assert (ROOT / path).is_file()
    assert "installer candidate" not in readme.lower()
    assert "deliberately not wired" not in readme.lower()
    assert "id=\"chat\"" in html and "src=\"/app.js\"" in html
    assert "/api/v1/chat/completions" in javascript and "sessionStorage" in javascript
    assert "boundedHistory" in javascript and "MAX_HISTORY_MESSAGES" in javascript and 'id="reset"' in html
    assert "innerHTML" not in javascript and "eval(" not in javascript
    assert "R740_INFERENCE_BASE_URL" in readme and "host.docker.internal" in install
    assert "R740_INFERENCE_API_KEY_FILE" in install and "YOUR_BACKEND_MODEL_ID" in readme
    assert (ROOT / "docs/OPERATIONS.md").is_file()
    print("PASS newcomer documentation and functional UI contract")


if __name__ == "__main__": main()
