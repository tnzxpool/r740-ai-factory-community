# SPDX-License-Identifier: LGPL-3.0-or-later
"""Local-only automatic routing candidate for the single-P40 R740.

The module is deliberately independent from the live portal/orchestrator.  It
contains no HTTP client and no model download path: callers must inject the
already-authenticated local model controller and task runner.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator, Protocol

from .config import SETTINGS

try:  # Linux production path.
    import fcntl  # type: ignore[import-not-found]
except ImportError:  # Windows-only host tests.
    fcntl = None  # type: ignore[assignment]


DEFAULT_MODEL = "qwen3.6-35b-a3b-iq4xs"
SAFETY_MODEL = "qwen3-8b"
ALLOWED_TASK_KINDS = {
    "general_chat",
    "structured_output",
    "coding",
    "frontend_ui",
    "vision_ocr",
    "document_retrieval",
    "image_generation",
    "tool_execution",
}


class RoutingError(ValueError):
    pass


class ExecutionError(RuntimeError):
    pass


class Controller(Protocol):
    def status(self) -> dict[str, Any]: ...
    def switch(self, model_id: str) -> dict[str, Any]: ...
    def restore_default(self, reason: str) -> dict[str, Any]: ...


@dataclass(frozen=True)
class Task:
    id: str
    kind: str
    depends_on: tuple[str, ...]
    sensitive: bool


@contextmanager
def exclusive_slot(path: Path | None = None) -> Iterator[None]:
    """Fail fast when another auto workflow owns the single GPU."""
    if fcntl is None:
        raise ExecutionError("POSIX workflow lock unavailable")
    path = path or SETTINGS.workflow_lock_path
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="ascii") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ExecutionError("motore occupato: workflow automatico gia in esecuzione") from exc
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _clean_tasks(raw_tasks: Any) -> list[Task]:
    if not isinstance(raw_tasks, list) or not 1 <= len(raw_tasks) <= 32:
        raise RoutingError("tasks must contain 1 to 32 items")
    clean: list[Task] = []
    ids: set[str] = set()
    for raw in raw_tasks:
        if not isinstance(raw, dict):
            raise RoutingError("each task must be an object")
        task_id = str(raw.get("id", "")).strip()
        kind = str(raw.get("kind", "")).strip()
        deps = raw.get("depends_on", [])
        if not task_id or len(task_id) > 64 or task_id in ids:
            raise RoutingError("task ids must be unique and bounded")
        if kind not in ALLOWED_TASK_KINDS:
            raise RoutingError(f"unsupported task kind: {kind}")
        if raw.get("requires_remote") or raw.get("provider") or raw.get("remote"):
            raise RoutingError("remote routes are disabled")
        if not isinstance(deps, list) or len(deps) > 16 or not all(isinstance(x, str) for x in deps):
            raise RoutingError("depends_on must be a bounded string list")
        ids.add(task_id)
        clean.append(Task(task_id, kind, tuple(dict.fromkeys(deps)), bool(raw.get("sensitive", False))))
    for task in clean:
        if task.id in task.depends_on or any(dep not in ids for dep in task.depends_on):
            raise RoutingError("invalid task dependency")
    return clean


def _routing_config(registry: dict[str, Any], *, require_execution: bool) -> dict[str, Any]:
    policy = registry.get("policy", {})
    routing = registry.get("routing", {})
    enabled = policy.get("automatic_routing_enabled") is True
    mode = routing.get("mode")
    if require_execution and (not enabled or mode != "local_auto"):
        raise RoutingError("automatic local routing is disabled")
    if not require_execution and (enabled, mode) not in {
        (False, "simulate"), (True, "local_auto"),
    }:
        raise RoutingError("routing preview policy is inconsistent")
    if policy.get("single_inference_job") is not True or policy.get("one_heavy_model_resident") is not True:
        raise RoutingError("single-P40 invariants are missing")
    if routing.get("allow_remote") is not False:
        raise RoutingError("remote routing must be explicitly false")
    if routing.get("default_model") != DEFAULT_MODEL:
        raise RoutingError("Qwen3.6 must remain the automatic fallback")
    return routing


def _eligible_models(registry: dict[str, Any], manager_status: dict[str, Any]) -> set[str]:
    registered = registry.get("models", {})
    live = manager_status.get("models", {})
    if not isinstance(registered, dict) or not isinstance(live, dict):
        raise RoutingError("invalid model catalog status")
    eligible = {
        model_id
        for model_id, spec in registered.items()
        if isinstance(spec, dict)
        and spec.get("catalog_state") == "qualified_local"
        and spec.get("available") is True
        and isinstance(live.get(model_id), dict)
        and live[model_id].get("available") is True
    }
    if DEFAULT_MODEL not in eligible:
        raise RoutingError("qualified Qwen3.6 fallback is unavailable")
    return eligible


def _choose_model(task: Task, profile: dict[str, Any], routing: dict[str, Any], eligible: set[str]) -> str:
    family_id = str(profile.get("task_routes", {}).get(task.kind, ""))
    family = routing.get("execution_families", {}).get(family_id)
    if not isinstance(family, dict):
        raise RoutingError(f"no execution family for {task.kind}")
    candidates = family.get("models", [])
    if not isinstance(candidates, list):
        raise RoutingError("invalid execution family")
    for model_id in candidates:
        if model_id in eligible:
            return model_id
    fallback = str(family.get("fallback", ""))
    if fallback == DEFAULT_MODEL and fallback in eligible and task.kind not in {"vision_ocr", "image_generation"}:
        return fallback
    raise RoutingError(f"no qualified local model for {task.kind}")


def _affinity_closure(seed: str, selected: dict[str, dict[str, Any]], remaining: set[str], completed: set[str]) -> int:
    """Count tasks that can run in one residency, including same-model chains."""
    model = selected[seed]["model_id"]
    virtual_done = set(completed)
    candidates = {task_id for task_id in remaining if selected[task_id]["model_id"] == model}
    progressed = True
    count = 0
    while progressed:
        progressed = False
        for task_id in sorted(candidates):
            if task_id not in virtual_done and set(selected[task_id]["task"].depends_on) <= virtual_done:
                virtual_done.add(task_id)
                count += 1
                progressed = True
    return count


def plan_workflow(
    registry: dict[str, Any],
    manager_status: dict[str, Any],
    profile_id: str,
    raw_tasks: Any,
    *,
    require_execution: bool = True,
) -> dict[str, Any]:
    routing = _routing_config(registry, require_execution=require_execution)
    profiles = routing.get("profiles", {})
    profile = profiles.get(profile_id)
    if not isinstance(profile, dict) or profile.get("enabled") is not True:
        raise RoutingError("profile unavailable")
    tasks = _clean_tasks(raw_tasks)
    eligible = _eligible_models(registry, manager_status)
    selected = {
        task.id: {"task": task, "model_id": _choose_model(task, profile, routing, eligible)}
        for task in tasks
    }
    for item in selected.values():
        spec = registry["models"][item["model_id"]]
        item["execution_mode"] = str(spec.get("execution_mode", "switch_managed"))
        if item["execution_mode"] not in {"switch_managed", "transactional"}:
            raise RoutingError("invalid model execution mode")
    active = str(manager_status.get("active_model", DEFAULT_MODEL))
    hot = active if active in eligible else DEFAULT_MODEL
    remaining = set(selected)
    completed: set[str] = set()
    groups: list[dict[str, Any]] = []
    while remaining:
        ready = [task_id for task_id in remaining if set(selected[task_id]["task"].depends_on) <= completed]
        if not ready:
            raise RoutingError("cyclic dependencies")
        ready_models = {selected[task_id]["model_id"] for task_id in ready}
        if hot in ready_models:
            chosen = hot
        else:
            scored = []
            for model in ready_models:
                seeds = [task_id for task_id in ready if selected[task_id]["model_id"] == model]
                score = max(_affinity_closure(seed, selected, remaining, completed) for seed in seeds)
                scored.append((-score, model))
            chosen = min(scored)[1]
        group_tasks: list[str] = []
        progressed = True
        while progressed:
            progressed = False
            for task_id in sorted(remaining):
                item = selected[task_id]
                if item["model_id"] == chosen and set(item["task"].depends_on) <= completed:
                    remaining.remove(task_id)
                    completed.add(task_id)
                    group_tasks.append(task_id)
                    progressed = True
                    break
        groups.append({
            "sequence": len(groups) + 1,
            "model_id": chosen,
            "task_ids": group_tasks,
            "switch_required": chosen != hot,
            "execution_mode": selected[group_tasks[0]]["execution_mode"],
        })
        hot = DEFAULT_MODEL if selected[group_tasks[0]]["execution_mode"] == "transactional" else chosen
    return {
        "mode": "local_auto" if require_execution else "local_auto_preview",
        "profile": profile_id,
        "groups": groups,
        "switch_count": sum(group["switch_required"] for group in groups),
        "privacy": "local_only",
        "default_model": DEFAULT_MODEL,
        "safety_model": SAFETY_MODEL,
        "eligible_models": sorted(eligible),
        "executed": False,
    }


def _single_healthy_model(status: dict[str, Any], target: str) -> bool:
    models = status.get("models")
    if not isinstance(models, dict):
        return False
    active_services = {
        model_id for model_id, spec in models.items()
        if isinstance(spec, dict) and spec.get("service_active") is True
    }
    return (
        status.get("active_model") == target
        and status.get("active_healthy") is True
        and status.get("graphics_state") == "cold"
        and active_services == {target}
    )


def _verified_restore(controller: Controller, reason: str) -> None:
    restored = controller.restore_default(reason)
    if (
        restored.get("model_id") != DEFAULT_MODEL
        or restored.get("healthy") is not True
        or restored.get("one_heavy") is not True
        or restored.get("graphics_cold") is not True
        or not _single_healthy_model(controller.status(), DEFAULT_MODEL)
    ):
        raise ExecutionError("Qwen3.6 restore failed; controller safety fallback may be active")


def execute_plan(
    plan: dict[str, Any],
    controller: Controller,
    run_task: Callable[[str, str], Any],
    *,
    slot: Callable[[], Any] = exclusive_slot,
) -> dict[str, Any]:
    """Execute sequentially; abort and restore Qwen3.6 on the first failure."""
    if plan.get("mode") != "local_auto" or plan.get("privacy") != "local_only":
        raise ExecutionError("untrusted routing plan")
    results: dict[str, Any] = {}
    events: list[dict[str, Any]] = []
    slot_acquired = False
    try:
        with slot():
            slot_acquired = True
            initial = controller.status()
            current = str(initial.get("active_model", DEFAULT_MODEL))
            if not _single_healthy_model(initial, current):
                if current in set(plan.get("eligible_models", [])):
                    repaired = controller.switch(current)
                    if (
                        repaired.get("active_model") != current
                        or repaired.get("active_healthy") is not True
                        or not _single_healthy_model(controller.status(), current)
                    ):
                        raise ExecutionError("initial model is unhealthy or violates one-heavy policy")
                else:
                    raise ExecutionError("initial model is unhealthy or ineligible")
            for group in plan.get("groups", []):
                target = str(group["model_id"])
                if target not in set(plan.get("eligible_models", [])):
                    raise ExecutionError("plan contains an ineligible model")
                execution_mode = str(group.get("execution_mode", ""))
                if execution_mode not in {"switch_managed", "transactional"}:
                    raise ExecutionError("plan contains an invalid execution mode")
                if execution_mode == "switch_managed" and current != target:
                    switched = controller.switch(target)
                    if (
                        switched.get("active_model") != target
                        or switched.get("active_healthy") is not True
                        or not _single_healthy_model(controller.status(), target)
                    ):
                        raise ExecutionError(f"model switch failed: {target}")
                    current = target
                    events.append({"event": "model_switch", "model_id": target})
                for task_id in group["task_ids"]:
                    results[task_id] = run_task(task_id, target)
                    events.append({"event": "task_complete", "task_id": task_id, "model_id": target})
                if execution_mode == "transactional":
                    live = controller.status()
                    if not _single_healthy_model(live, DEFAULT_MODEL):
                        _verified_restore(controller, f"transactional runner {target} did not restore default")
                    current = DEFAULT_MODEL
            if current != DEFAULT_MODEL:
                _verified_restore(controller, "automatic workflow complete")
                events.append({"event": "default_restored", "model_id": DEFAULT_MODEL})
    except Exception as exc:
        if not slot_acquired:
            raise ExecutionError(str(exc)) from exc
        try:
            rollback = controller.restore_default(f"automatic workflow aborted: {type(exc).__name__}")
        except Exception as rollback_exc:
            raise ExecutionError("workflow failed and Qwen3.6 rollback failed") from rollback_exc
        if (
            rollback.get("model_id") != DEFAULT_MODEL
            or rollback.get("healthy") is not True
            or rollback.get("one_heavy") is not True
            or rollback.get("graphics_cold") is not True
            or not _single_healthy_model(controller.status(), DEFAULT_MODEL)
        ):
            raise ExecutionError("workflow failed; Qwen3.6 unavailable, inspect safety fallback") from exc
        raise ExecutionError(f"workflow aborted and Qwen3.6 restored: {type(exc).__name__}") from exc
    return {"ok": True, "results": results, "events": events, "final_model": DEFAULT_MODEL}


def user_profiles(registry: dict[str, Any]) -> list[dict[str, str]]:
    """Small, model-name-free projection for the ordinary-user UI."""
    routing = registry.get("routing", {})
    profiles = routing.get("profiles", {})
    return [
        {"id": key, "label": str(value["label"]), "description": str(value["description"])}
        for key, value in profiles.items()
        if isinstance(value, dict) and value.get("enabled") is True and value.get("user_visible") is True
    ][:4]


def admin_models(registry: dict[str, Any], manager_status: dict[str, Any]) -> list[str]:
    """Technical selector projection: installed and qualified at this instant."""
    return sorted(
        model_id for model_id in _eligible_models(registry, manager_status)
        if registry["models"][model_id].get("selector_visible", True) is True
    )

