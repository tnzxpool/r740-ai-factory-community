# SPDX-License-Identifier: LGPL-3.0-or-later
from __future__ import annotations

from contextlib import contextmanager
import copy
import json
from pathlib import Path

from r740_core import autorouting as ar


HERE = Path(__file__).resolve().parent
REGISTRY = json.loads((HERE / "autorouting-enabled.fixture.json").read_text(encoding="utf-8"))


def manager(*, active: str = ar.DEFAULT_MODEL, unavailable: set[str] | None = None):
    unavailable = unavailable or set()
    return {
        "active_model": active,
        "active_healthy": True,
        "graphics_state": "cold",
        "models": {
            model_id: {
                "available": model_id not in unavailable,
                "service_active": model_id == active,
            }
            for model_id in REGISTRY["models"]
        },
    }


class FakeController:
    def __init__(self, status, *, fail_switch: str | None = None, fail_restore: bool = False):
        self.value = copy.deepcopy(status)
        self.fail_switch = fail_switch
        self.fail_restore = fail_restore
        self.calls = []

    def status(self):
        return copy.deepcopy(self.value)

    def switch(self, model_id):
        self.calls.append(("switch", model_id))
        if model_id == self.fail_switch:
            return {"active_model": model_id, "active_healthy": False}
        self.value["active_model"] = model_id
        self.value["active_healthy"] = True
        for candidate in self.value["models"].values():
            candidate["service_active"] = False
        self.value["models"][model_id]["service_active"] = True
        return {"active_model": model_id, "active_healthy": True}

    def restore_default(self, reason):
        self.calls.append(("restore", reason))
        if self.fail_restore:
            self.value = manager(active=ar.SAFETY_MODEL)
            return {"model_id": ar.SAFETY_MODEL, "healthy": True, "one_heavy": True, "graphics_cold": True}
        self.value["active_model"] = ar.DEFAULT_MODEL
        self.value["active_healthy"] = True
        self.value["graphics_state"] = "cold"
        for candidate in self.value["models"].values():
            candidate["service_active"] = False
        self.value["models"][ar.DEFAULT_MODEL]["service_active"] = True
        return {"model_id": ar.DEFAULT_MODEL, "healthy": True, "one_heavy": True, "graphics_cold": True}


@contextmanager
def slot():
    yield


def rejected(fn, contains):
    try:
        fn()
    except (ar.RoutingError, ar.ExecutionError) as exc:
        assert contains in str(exc), exc
    else:
        raise AssertionError(f"expected rejection containing {contains}")


tasks = [
    {"id": "understand", "kind": "general_chat"},
    {"id": "json", "kind": "structured_output", "depends_on": ["understand"]},
    {"id": "code", "kind": "coding", "depends_on": ["understand"]},
    {"id": "final", "kind": "general_chat", "depends_on": ["json", "code"]},
]
plan = ar.plan_workflow(REGISTRY, manager(), "auto", tasks)
assert plan["privacy"] == "local_only" and plan["default_model"] == ar.DEFAULT_MODEL
assert [g["model_id"] for g in plan["groups"]] == [ar.DEFAULT_MODEL, "glm-4.7-flash", ar.DEFAULT_MODEL]
assert plan["groups"][1]["task_ids"] == ["code", "json"]

# A same-model dependency chain stays in one residency group.
chain = ar.plan_workflow(REGISTRY, manager(active="glm-4.7-flash"), "structured", [
    {"id": "a", "kind": "coding"},
    {"id": "b", "kind": "structured_output", "depends_on": ["a"]},
    {"id": "c", "kind": "tool_execution", "depends_on": ["b"]},
])
assert len(chain["groups"]) == 1 and chain["groups"][0]["task_ids"] == ["a", "b", "c"]

# Registry qualification alone is insufficient: live controller availability is mandatory.
fallback = ar.plan_workflow(REGISTRY, manager(unavailable={"glm-4.7-flash"}), "auto", [
    {"id": "json", "kind": "structured_output"}
])
assert fallback["groups"][0]["model_id"] == ar.DEFAULT_MODEL
rejected(lambda: ar.plan_workflow(REGISTRY, manager(unavailable={ar.DEFAULT_MODEL}), "auto", tasks), "fallback is unavailable")

# Remote hints and incomplete single-P40 policy fail closed.
rejected(lambda: ar.plan_workflow(REGISTRY, manager(), "auto", [{"id": "x", "kind": "coding", "requires_remote": True}]), "remote routes")
bad = copy.deepcopy(REGISTRY); bad["routing"]["allow_remote"] = True
rejected(lambda: ar.plan_workflow(bad, manager(), "auto", tasks), "remote routing")
bad = copy.deepcopy(REGISTRY); bad["policy"]["single_inference_job"] = False
rejected(lambda: ar.plan_workflow(bad, manager(), "auto", tasks), "single-P40")
bad = copy.deepcopy(REGISTRY); bad["policy"]["automatic_routing_enabled"] = False
rejected(lambda: ar.plan_workflow(bad, manager(), "auto", tasks), "disabled")

# Plan canary is available while both execution gates remain OFF/simulate.
preview_registry = copy.deepcopy(REGISTRY)
preview_registry["policy"]["automatic_routing_enabled"] = False
preview_registry["routing"]["mode"] = "simulate"
preview = ar.plan_workflow(preview_registry, manager(), "auto", tasks, require_execution=False)
assert preview["mode"] == "local_auto_preview" and preview["executed"] is False
rejected(lambda: ar.execute_plan(preview, FakeController(manager()), lambda *_: True, slot=slot), "untrusted")

# Candidate/non-installed models never become eligible even if a fake live status says available.
assert "not-installed" not in plan["eligible_models"]
assert "glm-ocr-q8" in plan["eligible_models"]
assert "glm-ocr-q8" not in ar.admin_models(REGISTRY, manager())
assert set(ar.admin_models(REGISTRY, manager())) == set(plan["eligible_models"]) - {"glm-ocr-q8"}
rejected(lambda: ar.plan_workflow(REGISTRY, manager(unavailable={"qwen3-vl-8b"}), "vision", [
    {"id": "image", "kind": "vision_ocr"}
]), "no qualified local model")

# Real execution is sequential, restores Qwen3.6 and records decisions without prompt contents.
controller = FakeController(manager())
seen = []
result = ar.execute_plan(plan, controller, lambda task, model: seen.append((task, model)) or task, slot=slot)
assert result["ok"] and result["final_model"] == ar.DEFAULT_MODEL
assert seen == [("understand", ar.DEFAULT_MODEL), ("code", "glm-4.7-flash"), ("json", "glm-4.7-flash"), ("final", ar.DEFAULT_MODEL)]
assert all(set(event) <= {"event", "task_id", "model_id"} for event in result["events"])

# Transactional workers own their GPU lifecycle and must return to healthy Qwen3.6.
transaction = ar.plan_workflow(REGISTRY, manager(), "auto", [
    {"id": "picture", "kind": "image_generation"}
])
assert transaction["groups"][0]["execution_mode"] == "transactional"
controller = FakeController(manager())
result = ar.execute_plan(transaction, controller, lambda task, model: {"task": task, "model": model}, slot=slot)
assert not any(call[0] == "switch" for call in controller.calls)
assert result["final_model"] == ar.DEFAULT_MODEL

# Any switch or task failure aborts the remaining work and restores Qwen3.6.
controller = FakeController(manager(), fail_switch="glm-4.7-flash")
rejected(lambda: ar.execute_plan(plan, controller, lambda *_: True, slot=slot), "Qwen3.6 restored")
assert controller.calls[-1][0] == "restore"

# An unhealthy active default is repaired before any task, never used as-is.
unhealthy = manager(); unhealthy["active_healthy"] = False
controller = FakeController(unhealthy)
result = ar.execute_plan(
    ar.plan_workflow(REGISTRY, unhealthy, "auto", [{"id": "x", "kind": "general_chat"}]),
    controller, lambda *_: "healthy", slot=slot,
)
assert result["ok"] and controller.calls[0] == ("switch", ar.DEFAULT_MODEL)

# A warm graphics pipeline counts as a second heavy resident and aborts before inference.
warm_graphics = manager(); warm_graphics["graphics_state"] = "warm"
controller = FakeController(warm_graphics)
ran = []
rejected(
    lambda: ar.execute_plan(
        ar.plan_workflow(REGISTRY, warm_graphics, "auto", [{"id": "x", "kind": "general_chat"}]),
        controller, lambda *_: ran.append(True), slot=slot,
    ),
    "Qwen3.6 restored",
)
assert not ran and controller.calls[-1][0] == "restore"

# A controller that leaves two heavy services active fails closed and rolls back.
class LeakyController(FakeController):
    def switch(self, model_id):
        result = super().switch(model_id)
        self.value["models"][ar.SAFETY_MODEL]["service_active"] = True
        return result

leaky = LeakyController(manager(active=ar.SAFETY_MODEL))
rejected(
    lambda: ar.execute_plan(
        ar.plan_workflow(REGISTRY, leaky.status(), "auto", [{"id": "x", "kind": "general_chat"}]),
        leaky, lambda *_: True, slot=slot,
    ),
    "Qwen3.6 restored",
)
controller = FakeController(manager())
rejected(lambda: ar.execute_plan(plan, controller, lambda task, _: (_ for _ in ()).throw(RuntimeError()) if task == "code" else True, slot=slot), "Qwen3.6 restored")
assert controller.calls[-1][0] == "restore"

# A failed Qwen3.6 restore is surfaced; the controller may have selected its 8B safety fallback.
controller = FakeController(manager(), fail_switch="glm-4.7-flash", fail_restore=True)
rejected(lambda: ar.execute_plan(plan, controller, lambda *_: True, slot=slot), "Qwen3.6 unavailable")

# Ordinary UI remains compact and model-name-free.
profiles = ar.user_profiles(REGISTRY)
assert len(profiles) == 4
assert not any("qwen" in json.dumps(item).lower() or "glm" in json.dumps(item).lower() for item in profiles)

print("PASS local_only live_qualification affinity_batch single_p40 qwen36_restore failure_abort compact_ui")

