# SPDX-License-Identifier: LGPL-3.0-or-later
"""Deterministic, fail-closed routing preview for the R740 model catalog.

This module never starts, stops or downloads a model. It accepts typed tasks,
validates them against the registry and returns a grouped execution preview.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any


ALLOWED_TASK_KINDS = {
    "general_chat", "structured_output", "coding", "frontend_ui",
    "vision_ocr", "document_retrieval", "image_generation", "tool_execution",
}
LOCAL_AUTO_STATES = {"qualified_local"}


class RoutingError(ValueError):
    pass


def _routing(registry: dict[str, Any]) -> dict[str, Any]:
    value = registry.get("routing")
    if not isinstance(value, dict) or value.get("mode") != "simulate":
        raise RoutingError("routing simulation is not configured")
    return value


def routing_snapshot(registry: dict[str, Any]) -> dict[str, Any]:
    routing = _routing(registry)
    profiles = routing.get("profiles", {})
    families = routing.get("execution_families", {})
    if not isinstance(profiles, dict) or not isinstance(families, dict):
        raise RoutingError("invalid routing registry")
    return {
        "mode": "simulate",
        "auto_enabled": False,
        "default_profile": routing.get("default_profile", "general"),
        "profiles": profiles,
        "execution_families": families,
        "approval_policy": routing.get("approval_policy", {}),
    }


def _validate_tasks(tasks: Any) -> list[dict[str, Any]]:
    if not isinstance(tasks, list) or not tasks or len(tasks) > 32:
        raise RoutingError("tasks must contain 1 to 32 items")
    clean: list[dict[str, Any]] = []
    ids: set[str] = set()
    for raw in tasks:
        if not isinstance(raw, dict):
            raise RoutingError("each task must be an object")
        task_id = str(raw.get("id", "")).strip()
        kind = str(raw.get("kind", "")).strip()
        if not task_id or len(task_id) > 64 or task_id in ids:
            raise RoutingError("task ids must be unique and bounded")
        if kind not in ALLOWED_TASK_KINDS:
            raise RoutingError(f"unsupported task kind: {kind}")
        dependencies = raw.get("depends_on", [])
        if not isinstance(dependencies, list) or not all(isinstance(x, str) for x in dependencies):
            raise RoutingError("depends_on must be a string list")
        if len(dependencies) > 16:
            raise RoutingError("too many dependencies")
        ids.add(task_id)
        clean.append({
            "id": task_id,
            "kind": kind,
            "depends_on": list(dict.fromkeys(dependencies)),
            "sensitive": bool(raw.get("sensitive", False)),
            "requires_remote": bool(raw.get("requires_remote", False)),
        })
    for task in clean:
        if task["id"] in task["depends_on"] or any(dep not in ids for dep in task["depends_on"]):
            raise RoutingError("invalid task dependency")
    return clean


def _select_model(
    task: dict[str, Any], profile: dict[str, Any], registry: dict[str, Any],
    *, allow_remote: bool,
) -> tuple[str, str, str]:
    families = _routing(registry)["execution_families"]
    models = registry.get("models", {})
    family_id = str(profile.get("task_routes", {}).get(task["kind"], ""))
    family = families.get(family_id)
    if not family:
        raise RoutingError(f"no execution family for {task['kind']}")
    candidates = list(family.get("models", []))
    fallback = str(family.get("fallback", "qwen3-8b"))
    if fallback not in candidates:
        candidates.append(fallback)
    for model_id in candidates:
        model = models.get(model_id, {})
        state = model.get("catalog_state")
        if state in LOCAL_AUTO_STATES:
            return model_id, family_id, "qualified_local"
        if state == "remote_optional" and allow_remote and not task["sensitive"]:
            return model_id, family_id, "remote_optional"
    raise RoutingError(f"no approved model for {task['kind']}")


def plan_workflow(
    registry: dict[str, Any], profile_id: str, tasks: Any,
    *, active_model: str = "qwen3-8b", allow_remote: bool = False,
) -> dict[str, Any]:
    """Return a preview only; no runtime action is ever performed."""
    routing = _routing(registry)
    profile = routing.get("profiles", {}).get(profile_id)
    if not isinstance(profile, dict) or not profile.get("enabled", False):
        raise RoutingError("profile unavailable")
    clean = _validate_tasks(tasks)
    selected: dict[str, dict[str, Any]] = {}
    for task in clean:
        model_id, family_id, location = _select_model(
            task, profile, registry, allow_remote=allow_remote
        )
        if task["requires_remote"] and location != "remote_optional":
            raise RoutingError("task explicitly requires a remote route")
        selected[task["id"]] = {**task, "model_id": model_id, "family": family_id, "location": location}

    remaining = {task["id"] for task in clean}
    completed: set[str] = set()
    groups: list[dict[str, Any]] = []
    hot = active_model
    while remaining:
        ready = [selected[task_id] for task_id in remaining if set(selected[task_id]["depends_on"]) <= completed]
        if not ready:
            raise RoutingError("cyclic dependencies")
        same_hot = [task for task in ready if task["model_id"] == hot]
        chosen_model = hot if same_hot else sorted({task["model_id"] for task in ready})[0]
        batch = sorted((task for task in ready if task["model_id"] == chosen_model), key=lambda x: x["id"])
        groups.append({
            "sequence": len(groups) + 1,
            "model_id": chosen_model,
            "execution_family": batch[0]["family"],
            "location": batch[0]["location"],
            "task_ids": [task["id"] for task in batch],
            "switch_required": chosen_model != hot,
        })
        hot = chosen_model
        for task in batch:
            remaining.remove(task["id"])
            completed.add(task["id"])

    remote_groups = [group for group in groups if group["location"] == "remote_optional"]
    return {
        "mode": "simulate",
        "executed": False,
        "profile": profile_id,
        "groups": groups,
        "switch_count": sum(bool(group["switch_required"]) for group in groups),
        "approval_required": bool(remote_groups),
        "approval_reasons": ["remote_provider"] if remote_groups else [],
        "privacy": "local_only" if not remote_groups else "contains_remote_route",
    }


