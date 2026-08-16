"""
NexusNode CLI — Authoritative Central API Response Normalization Layer
Normalizes varying backend response shapes (top-level lists, nested objects, legacy keys)
into canonical schemas without synthesizing fake data or hiding missing fields.
"""

from typing import Any, Optional


def normalize_list(resp: Any, preferred_key: Optional[str] = None) -> list:
    """
    Normalizes response into a Python list.
    Supports top-level lists and known wrapped dictionaries without synthesizing fake records.
    """
    if isinstance(resp, list):
        return resp
    if isinstance(resp, dict):
        if preferred_key and preferred_key in resp and isinstance(resp[preferred_key], list):
            return resp[preferred_key]
        for key in ["items", "models", "files", "tasks", "events", "backups", "jobs", "shares", "users", "rows", "results", "active_tasks"]:
            if key in resp and isinstance(resp[key], list):
                return resp[key]
    return []


def normalize_dict(resp: Any, preferred_key: Optional[str] = None) -> dict:
    """
    Normalizes response into a Python dict.
    """
    if isinstance(resp, dict):
        if preferred_key and preferred_key in resp and isinstance(resp[preferred_key], dict):
            return resp[preferred_key]
        return resp
    return {}


def normalize_models(resp: Any) -> list[dict]:
    """
    Normalizes /api/ai/models response into list of model dictionaries.
    """
    return normalize_list(resp, "models")


def normalize_task(raw_task: Any) -> dict:
    """
    Normalizes a single task payload into the canonical task model.
    Preserves raw status/stage separation and flags internal state contradictions.
    """
    if not isinstance(raw_task, dict):
        return {
            "task_id": "invalid",
            "task_type": "unknown",
            "title": "Invalid Task Object",
            "status": "UNKNOWN",
            "stage": "UNKNOWN",
            "progress": None,
            "speed_bps": None,
            "eta_seconds": None,
            "output_path": None,
            "error": "Malformed payload",
            "result": None,
            "created_at": None,
            "started_at": None,
            "completed_at": None,
            "owner": "unknown",
            "has_contradiction": False,
            "contradiction_warning": None
        }

    task_id = raw_task.get("task_id") or raw_task.get("id") or "unknown"
    task_type = raw_task.get("task_type") or raw_task.get("type") or "generic"
    title = raw_task.get("title") or raw_task.get("description") or f"Task {task_id}"
    status = str(raw_task.get("status") or "QUEUED").upper()
    stage = str(raw_task.get("stage") or "").upper() if raw_task.get("stage") else ""

    progress_raw = raw_task.get("progress")
    progress = None
    if progress_raw is not None:
        try:
            progress = float(progress_raw)
        except (ValueError, TypeError):
            progress = None

    speed_bps = raw_task.get("speed_bps")
    eta_seconds = raw_task.get("eta_seconds")
    output_path = raw_task.get("output_path") or raw_task.get("file_path") or raw_task.get("filepath")
    error = raw_task.get("error") or raw_task.get("error_message") or raw_task.get("message") if status == "FAILED" else raw_task.get("error")
    result = raw_task.get("result")
    created_at = raw_task.get("created_at")
    started_at = raw_task.get("started_at")
    completed_at = raw_task.get("completed_at")
    owner = raw_task.get("owner_user_id") or raw_task.get("owner") or "system"

    # Detect state contradictions
    has_contradiction = False
    contradiction_warning = None
    if status in ["COMPLETED", "FAILED", "CANCELLED"] and stage == "QUEUED":
        has_contradiction = True
        contradiction_warning = f"STATE CONTRADICTION: backend reported STATUS={status} but STAGE=QUEUED"

    return {
        "task_id": task_id,
        "task_type": task_type,
        "title": title,
        "status": status,
        "stage": stage,
        "progress": progress,
        "speed_bps": speed_bps,
        "eta_seconds": eta_seconds,
        "output_path": output_path,
        "error": error,
        "result": result,
        "created_at": created_at,
        "started_at": started_at,
        "completed_at": completed_at,
        "owner": owner,
        "has_contradiction": has_contradiction,
        "contradiction_warning": contradiction_warning,
        "raw": raw_task
    }


def normalize_tasks(resp: Any) -> list[dict]:
    """
    Normalizes /api/tasks response into list of canonical task dictionaries.
    """
    raw_list = normalize_list(resp, "tasks")
    return [normalize_task(t) for t in raw_list]


def normalize_system_status(resp: Any) -> dict:
    """
    Normalizes /api/system/status payload.
    Maps authoritative fields without synthesizing fake zero values for missing data.
    """
    if not isinstance(resp, dict):
        return {}

    appliance = resp.get("appliance", {})
    memory = resp.get("memory", {}) or resp.get("ram", {})
    disk = resp.get("disk", {}) or resp.get("storage", {})
    battery = resp.get("battery", {}) or resp.get("device", {})
    thermal = resp.get("thermal", {}) or resp.get("device", {})
    services = resp.get("services", {})
    tasks = resp.get("tasks", {})
    server = resp.get("server", {}) or resp.get("system", {})
    process = resp.get("nexusnode_process", {}) or resp.get("process", {})
    rag = resp.get("rag", {})
    cpu = resp.get("cpu", {}) or resp.get("device", {})

    return {
        "server": server,
        "appliance": appliance,
        "memory": memory,
        "disk": disk,
        "battery": battery,
        "thermal": thermal,
        "services": services,
        "tasks": tasks,
        "process": process,
        "rag": rag,
        "cpu": cpu,
        "raw": resp
    }


def normalize_services(resp: Any) -> dict[str, dict]:
    """
    Normalizes /api/services/status into a mapping of service_name -> service_data dict.
    Deduplicates alias keys (e.g. sshd -> ssh).
    """
    if not isinstance(resp, dict):
        return {}

    raw_svcs = resp.get("services", resp)
    if not isinstance(raw_svcs, dict):
        return {}

    clean_svcs = {}
    for name, data in raw_svcs.items():
        if not isinstance(data, dict):
            continue
        # Deduplicate sshd if ssh exists
        if name == "sshd" and "ssh" in raw_svcs:
            continue
        clean_svcs[name] = data

    return clean_svcs


def normalize_rag(resp: Any) -> dict:
    """
    Normalizes /api/rag/diagnostics response.
    """
    if not isinstance(resp, dict):
        return {}

    return {
        "backend": resp.get("backend") or resp.get("algorithm") or "SQLite FTS5",
        "database_file": resp.get("database_file") or resp.get("db_file"),
        "database_size_kb": resp.get("database_size_kb") if "database_size_kb" in resp else (round(resp.get("index_size_bytes", 0) / 1024, 2) if "index_size_bytes" in resp else None),
        "document_count": resp.get("document_count") if "document_count" in resp else resp.get("indexed_documents_count"),
        "chunk_count": resp.get("chunk_count") if "chunk_count" in resp else resp.get("chunks_count"),
        "avg_chunk_tokens": resp.get("avg_chunk_tokens"),
        "largest_document": resp.get("largest_document"),
        "source_folders": resp.get("source_folders", []),
        "last_rebuild_time": resp.get("last_rebuild_time") or resp.get("last_indexed_at"),
        "memory_estimate_mb": resp.get("memory_estimate_mb"),
        "state": resp.get("state") or resp.get("status") or "UNKNOWN",
        "raw": resp
    }
