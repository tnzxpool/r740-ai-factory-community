# SPDX-License-Identifier: LGPL-3.0-or-later
from pathlib import Path

source = (Path(__file__).resolve().parents[1] / "src/sandbox_api.py").read_text(encoding="utf-8")
compile(source, "sandbox_api.py", "exec")

for marker in (
    "@app.delete('/v1/users/{username}')",
    "if job_lock.locked()",
    "path.parent.resolve()!=root",
    "path.is_symlink()",
    "PROJECT_MIN<=project_id<=PROJECT_MAX",
    "shutil.rmtree(path)",
    "'setquota','-P',str(project_id),'0','0','0','0',QUOTA_MOUNT",
    "delete from users where username=?",
    "range(PROJECT_MIN,PROJECT_MAX+1)",
):
    assert marker in source, marker

print("SANDBOX_DELETE_CONTRACT_OK")

for marker in ("'--network','none'", "'--read-only'", "'--pids-limit','64'", "'--memory','512m'", "'--cap-drop','all'", "'no-new-privileges'", "Guest"):
    assert marker in source, marker
