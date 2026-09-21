"""
NexusNode — Agent Vault Semantic Service
Enforces strict allowlist root containment, path traversal prevention, symlink escape checks,
file size budgets, binary file detection, and structural untrusted content boundaries.
"""

import os
import time
import mimetypes
import hashlib
import shutil
import logging
from typing import Dict, Any, List, Optional, Tuple

import config
from .errors import NexusAgentError, InternalError
from .models import ExecutionResult

logger = logging.getLogger("NEXUS_AGENT_VAULT")


class VaultPathError(NexusAgentError):
    code = "INVALID_PATH"


class VaultAccessError(NexusAgentError):
    code = "ACCESS_DENIED"


class VaultService:
    """Provides safe, scoped semantic Vault operations for AI agents."""

    def __init__(self, agent_vault_root: Optional[str] = None, rag_service=None):
        self.agent_vault_root = os.path.realpath(agent_vault_root or config.AGENT_VAULT_ROOT)
        self.rag_service = rag_service
        os.makedirs(self.agent_vault_root, exist_ok=True)

    def _resolve_safe_path(self, rel_path: Optional[str]) -> str:
        """
        Resolves rel_path strictly within self.agent_vault_root.
        Prevents path traversal, parent escapes (..), absolute escapes, and symlink targets outside root.
        """
        if not rel_path:
            return self.agent_vault_root

        # Normalize separators
        clean_rel = rel_path.strip().replace("\\", "/").lstrip("/")
        
        # Guard against traversal tokens
        parts = clean_rel.split("/")
        if ".." in parts:
            raise VaultPathError("Path traversal elements ('..') are strictly prohibited.")

        resolved_target = os.path.realpath(os.path.join(self.agent_vault_root, clean_rel))

        # Strict containment verification
        root_real = os.path.realpath(self.agent_vault_root)
        try:
            common = os.path.commonpath([resolved_target, root_real])
        except ValueError:
            raise VaultPathError("Cross-drive or invalid path resolution.")

        if common != root_real:
            raise VaultAccessError(f"Target path escapes agent-visible vault root.")

        return resolved_target

    def _get_relative_path(self, absolute_path: str) -> str:
        """Returns relative path from agent_vault_root with forward slashes."""
        rel = os.path.relpath(absolute_path, self.agent_vault_root)
        return "" if rel == "." else rel.replace("\\", "/")

    def _is_binary(self, file_path: str) -> bool:
        """Checks if file is binary by inspecting the first 1024 bytes for null bytes."""
        try:
            with open(file_path, "rb") as f:
                chunk = f.read(1024)
                return b"\x00" in chunk
        except Exception:
            return True

    def list_files(self, user_id: str, params: Optional[Dict[str, Any]] = None) -> ExecutionResult:
        """
        Lists files and subdirectories strictly within the agent-visible Vault root.
        Params:
          path (str, optional): Subdirectory to list.
          recursive (bool, default False): Whether to recurse (max depth 2).
        """
        params = params or {}
        subpath = params.get("path", "")
        recursive = bool(params.get("recursive", False))
        now = time.time()

        try:
            target_dir = self._resolve_safe_path(subpath)
        except NexusAgentError as ne:
            return ExecutionResult(
                ok=False,
                operation="vault.list",
                source="local",
                provider="local_vault",
                error=ne.message,
                error_code=ne.code,
                fetched_at=now
            )

        if not os.path.exists(target_dir):
            return ExecutionResult(
                ok=False,
                operation="vault.list",
                source="local",
                provider="local_vault",
                error=f"Directory '{subpath}' not found in agent vault.",
                error_code="NOT_FOUND",
                fetched_at=now
            )

        if not os.path.isdir(target_dir):
            return ExecutionResult(
                ok=False,
                operation="vault.list",
                source="local",
                provider="local_vault",
                error=f"Path '{subpath}' is a file, not a directory.",
                error_code="INVALID_PATH",
                fetched_at=now
            )

        items = []
        try:
            def scan_dir(dpath: str, depth: int):
                for entry in os.scandir(dpath):
                    if entry.name.startswith("."):
                        continue
                    
                    real_entry_path = os.path.realpath(entry.path)
                    # Verify entry is inside root
                    if os.path.commonpath([real_entry_path, self.agent_vault_root]) != self.agent_vault_root:
                        continue

                    rel = self._get_relative_path(real_entry_path)
                    stat = entry.stat()
                    is_dir = entry.is_dir()
                    mime_type, _ = mimetypes.guess_type(entry.name)

                    items.append({
                        "name": entry.name,
                        "path": rel,
                        "is_dir": is_dir,
                        "size_bytes": 0 if is_dir else stat.st_size,
                        "modified_at": stat.st_mtime,
                        "mime_type": "directory" if is_dir else (mime_type or "application/octet-stream")
                    })

                    if is_dir and recursive and depth < 2:
                        scan_dir(real_entry_path, depth + 1)

            scan_dir(target_dir, depth=0)
            items.sort(key=lambda x: (not x["is_dir"], x["name"].lower()))

            return ExecutionResult(
                ok=True,
                operation="vault.list",
                source="local",
                provider="local_vault",
                data={
                    "current_path": self._get_relative_path(target_dir),
                    "total_items": len(items),
                    "items": items[:100]  # Bound to max 100 items for output budgeting
                },
                fetched_at=now
            )
        except Exception as e:
            logger.exception(f"Error listing agent vault: {e}")
            return ExecutionResult(
                ok=False,
                operation="vault.list",
                source="local",
                provider="local_vault",
                error=f"Failed to list vault directory: {str(e)}",
                error_code="INTERNAL_ERROR",
                fetched_at=now
            )

    def read_file(self, user_id: str, params: Optional[Dict[str, Any]] = None) -> ExecutionResult:
        """
        Reads content from a file inside the agent-visible Vault root with pagination and untrusted boundaries.
        Params:
          path (str, required): Target relative file path.
          offset (int, default 0): Character offset to start reading from.
          limit_chars (int, default 4000, max 10000): Maximum characters to return.
        """
        params = params or {}
        file_rel = params.get("path")
        offset = max(0, int(params.get("offset", 0)))
        limit_chars = min(10000, max(100, int(params.get("limit_chars", 4000))))
        now = time.time()

        if not file_rel:
            return ExecutionResult(
                ok=False,
                operation="vault.read",
                source="local",
                provider="local_vault",
                error="Parameter 'path' is required for vault.read.",
                error_code="INVALID_PARAMS",
                fetched_at=now
            )

        try:
            target_file = self._resolve_safe_path(file_rel)
        except NexusAgentError as ne:
            return ExecutionResult(
                ok=False,
                operation="vault.read",
                source="local",
                provider="local_vault",
                error=ne.message,
                error_code=ne.code,
                fetched_at=now
            )

        if not os.path.exists(target_file) or not os.path.isfile(target_file):
            return ExecutionResult(
                ok=False,
                operation="vault.read",
                source="local",
                provider="local_vault",
                error=f"File '{file_rel}' not found in agent vault.",
                error_code="NOT_FOUND",
                fetched_at=now
            )

        # File size check (max 5 MB for direct read)
        file_size = os.path.getsize(target_file)
        if file_size > 5 * 1024 * 1024:
            return ExecutionResult(
                ok=False,
                operation="vault.read",
                source="local",
                provider="local_vault",
                error=f"File '{file_rel}' exceeds maximum direct read size limit (5 MB). Use vault.search to query indexed sections.",
                error_code="FILE_TOO_LARGE",
                metadata={"file_size_bytes": file_size},
                fetched_at=now
            )

        # PDF check & text extraction
        if target_file.lower().endswith(".pdf"):
            try:
                from pypdf import PdfReader
                reader = PdfReader(target_file)
                pdf_text_parts = []
                for i, page in enumerate(reader.pages):
                    txt = page.extract_text() or ""
                    pdf_text_parts.append(f"--- Page {i+1} ---\n{txt}")
                full_text = "\n\n".join(pdf_text_parts)
                total_chars = len(full_text)
                chunk = full_text[offset : offset + limit_chars]
                has_more = (offset + limit_chars) < total_chars
                rel_path = self._get_relative_path(target_file)
                envelope = (
                    f'<untrusted_document_content path="{rel_path}" type="pdf_extracted_text" offset="{offset}" total_chars="{total_chars}">\n'
                    f'{chunk}\n'
                    f'</untrusted_document_content>'
                )
                return ExecutionResult(
                    ok=True,
                    operation="vault.read",
                    source="local",
                    provider="local_vault",
                    data={
                        "content_type": "extracted_pdf_text",
                        "path": rel_path,
                        "size_bytes": file_size,
                        "mime_type": "application/pdf",
                        "offset": offset,
                        "limit_chars": limit_chars,
                        "total_chars": total_chars,
                        "page_count": len(reader.pages),
                        "has_more": has_more,
                        "text": chunk,
                        "envelope": envelope
                    },
                    fetched_at=now
                )
            except Exception as pdf_err:
                logger.warning(f"PDF extraction failed for '{target_file}': {pdf_err}")

        # General binary check
        mime_type, _ = mimetypes.guess_type(target_file)
        if self._is_binary(target_file):
            return ExecutionResult(
                ok=True,
                operation="vault.read",
                source="local",
                provider="local_vault",
                data={
                    "content_type": "binary_document_metadata",
                    "path": self._get_relative_path(target_file),
                    "size_bytes": file_size,
                    "mime_type": mime_type or "application/octet-stream",
                    "is_binary": True,
                    "message": "Binary file cannot be returned as text. Download or specialized processing required."
                },
                fetched_at=now
            )

        try:
            with open(target_file, "r", encoding="utf-8", errors="replace") as f:
                full_text = f.read()

            total_chars = len(full_text)
            chunk = full_text[offset : offset + limit_chars]
            has_more = (offset + limit_chars) < total_chars
            rel_path = self._get_relative_path(target_file)

            envelope = (
                f'<untrusted_document_content path="{rel_path}" offset="{offset}" total_chars="{total_chars}">\n'
                f'{chunk}\n'
                f'</untrusted_document_content>'
            )

            return ExecutionResult(
                ok=True,
                operation="vault.read",
                source="local",
                provider="local_vault",
                data={
                    "content_type": "untrusted_document",
                    "path": rel_path,
                    "size_bytes": file_size,
                    "mime_type": mime_type or "text/plain",
                    "offset": offset,
                    "limit_chars": limit_chars,
                    "total_chars": total_chars,
                    "has_more": has_more,
                    "text": chunk,
                    "envelope": envelope
                },
                fetched_at=now
            )
        except Exception as e:
            logger.exception(f"Error reading file '{target_file}': {e}")
            return ExecutionResult(
                ok=False,
                operation="vault.read",
                source="local",
                provider="local_vault",
                error=f"Failed to read file: {str(e)}",
                error_code="INTERNAL_ERROR",
                fetched_at=now
            )

    def search_vault(self, user_id: str, params: Optional[Dict[str, Any]] = None) -> ExecutionResult:
        """
        Searches content strictly within the agent-visible Vault root.
        Params:
          query (str, required): Search query keywords.
          max_results (int, default 5, max 20): Maximum snippet matches to return.
        """
        params = params or {}
        query = (params.get("query") or "").strip()
        max_results = min(20, max(1, int(params.get("max_results", 5))))
        now = time.time()

        if not query:
            return ExecutionResult(
                ok=False,
                operation="vault.search",
                source="local",
                provider="local_vault",
                error="Parameter 'query' is required for vault.search.",
                error_code="INVALID_PARAMS",
                fetched_at=now
            )

        results = []

        # 1. Use RAG Service if available and filter to agent_vault_root
        if self.rag_service and hasattr(self.rag_service, "search"):
            try:
                rag_hits = self.rag_service.search(query, top_k=max_results * 2)
                for hit in rag_hits:
                    fpath = hit.get("file_path") or ""
                    # Strict check: is fpath within agent_vault_root?
                    try:
                        abs_hit = os.path.realpath(fpath)
                        if os.path.commonpath([abs_hit, self.agent_vault_root]) == self.agent_vault_root:
                            rel = self._get_relative_path(abs_hit)
                            snippet = hit.get("text", "")[:400]
                            results.append({
                                "content_type": "untrusted_search_result",
                                "path": rel,
                                "snippet": snippet,
                                "score": hit.get("score", 1.0)
                            })
                            if len(results) >= max_results:
                                break
                    except Exception:
                        continue
            except Exception as e:
                logger.warning(f"RAG search error in vault.search: {e}")

        # 2. If no RAG results, perform localized text scan over agent_vault_root
        if not results:
            try:
                for root, _, files in os.walk(self.agent_vault_root):
                    for fname in files:
                        if fname.startswith("."):
                            continue
                        fpath = os.path.join(root, fname)
                        if self._is_binary(fpath) or os.path.getsize(fpath) > 2 * 1024 * 1024:
                            continue
                        
                        try:
                            with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                                content = f.read()
                            if query.lower() in content.lower():
                                rel = self._get_relative_path(fpath)
                                idx = content.lower().find(query.lower())
                                start_idx = max(0, idx - 100)
                                end_idx = min(len(content), idx + 300)
                                snippet = content[start_idx:end_idx].strip()
                                results.append({
                                    "content_type": "untrusted_search_result",
                                    "path": rel,
                                    "snippet": snippet,
                                    "score": 1.0
                                })
                                if len(results) >= max_results:
                                    break
                        except Exception:
                            continue
                    if len(results) >= max_results:
                        break
            except Exception as e:
                logger.warning(f"Fallback vault search error: {e}")

        return ExecutionResult(
            ok=True,
            operation="vault.search",
            source="local",
            provider="local_vault",
            data={
                "query": query,
                "total_matches": len(results),
                "results": results
            },
            fetched_at=now
        )

    def mkdir(self, user_id: str, params: Optional[Dict[str, Any]] = None) -> ExecutionResult:
        """
        Creates a new directory inside the agent-visible Vault root.
        Params:
          path (str, required): Relative path of directory to create.
          parents (bool, default True): Whether to create parent directories if missing.
        """
        params = params or {}
        dir_rel = (params.get("path") or "").strip()
        parents = bool(params.get("parents", True))
        now = time.time()

        if not dir_rel:
            return ExecutionResult(
                ok=False,
                operation="vault.mkdir",
                source="local",
                provider="local_vault",
                error="Parameter 'path' is required for vault.mkdir.",
                error_code="INVALID_PARAMS",
                fetched_at=now
            )

        try:
            target_dir = self._resolve_safe_path(dir_rel)
        except NexusAgentError as ne:
            return ExecutionResult(
                ok=False,
                operation="vault.mkdir",
                source="local",
                provider="local_vault",
                error=ne.message,
                error_code=ne.code,
                fetched_at=now
            )

        if os.path.exists(target_dir):
            if os.path.isdir(target_dir):
                return ExecutionResult(
                    ok=True,
                    operation="vault.mkdir",
                    source="local",
                    provider="local_vault",
                    data={
                        "path": self._get_relative_path(target_dir),
                        "already_existed": True,
                        "created": False
                    },
                    fetched_at=now
                )
            else:
                return ExecutionResult(
                    ok=False,
                    operation="vault.mkdir",
                    source="local",
                    provider="local_vault",
                    error=f"A non-directory file already exists at '{dir_rel}'.",
                    error_code="FILE_EXISTS",
                    fetched_at=now
                )

        try:
            os.makedirs(target_dir, exist_ok=parents)
            rel_created = self._get_relative_path(target_dir)
            return ExecutionResult(
                ok=True,
                operation="vault.mkdir",
                source="local",
                provider="local_vault",
                data={
                    "path": rel_created,
                    "created": True,
                    "created_at": now
                },
                fetched_at=now
            )
        except Exception as e:
            return ExecutionResult(
                ok=False,
                operation="vault.mkdir",
                source="local",
                provider="local_vault",
                error=f"Failed to create directory: {str(e)}",
                error_code="INTERNAL_ERROR",
                fetched_at=now
            )

    def create_file(self, user_id: str, params: Optional[Dict[str, Any]] = None) -> ExecutionResult:
        """
        Creates a new text/markdown file inside the agent-visible Vault root.
        Fails with FILE_EXISTS if the file already exists (protects against accidental overwrite).
        Params:
          path (str, required): Target relative file path.
          content (str, required): Text content to write.
          source (str, optional): Provenance source (default 'spark_generated').
        """
        params = params or {}
        file_rel = (params.get("path") or "").strip()
        content = params.get("content", "")
        source_prov = params.get("source", "spark_generated")
        now = time.time()

        if not file_rel:
            return ExecutionResult(
                ok=False,
                operation="vault.create",
                source="local",
                provider="local_vault",
                error="Parameter 'path' is required for vault.create.",
                error_code="INVALID_PARAMS",
                fetched_at=now
            )

        try:
            target_file = self._resolve_safe_path(file_rel)
        except NexusAgentError as ne:
            return ExecutionResult(
                ok=False,
                operation="vault.create",
                source="local",
                provider="local_vault",
                error=ne.message,
                error_code=ne.code,
                fetched_at=now
            )

        if os.path.exists(target_file):
            return ExecutionResult(
                ok=False,
                operation="vault.create",
                source="local",
                provider="local_vault",
                error=f"File '{file_rel}' already exists. Use vault.write to update existing files.",
                error_code="FILE_EXISTS",
                fetched_at=now
            )

        # File size budget check (max 10MB)
        content_bytes = content.encode("utf-8") if isinstance(content, str) else bytes(content)
        if len(content_bytes) > 10 * 1024 * 1024:
            return ExecutionResult(
                ok=False,
                operation="vault.create",
                source="local",
                provider="local_vault",
                error="Content exceeds maximum file creation size limit (10 MB).",
                error_code="FILE_TOO_LARGE",
                fetched_at=now
            )

        try:
            parent_dir = os.path.dirname(target_file)
            if parent_dir:
                os.makedirs(parent_dir, exist_ok=True)

            # Atomic write via temp file in same directory
            temp_path = f"{target_file}.tmp_{int(now * 1000)}"
            with open(temp_path, "wb") as f:
                f.write(content_bytes)
            os.replace(temp_path, target_file)

            sha256_hash = hashlib.sha256(content_bytes).hexdigest()
            rel_path = self._get_relative_path(target_file)

            return ExecutionResult(
                ok=True,
                operation="vault.create",
                source="local",
                provider="local_vault",
                data={
                    "path": rel_path,
                    "size_bytes": len(content_bytes),
                    "sha256": sha256_hash,
                    "created_by": user_id,
                    "created_at": now,
                    "provenance": source_prov
                },
                fetched_at=now
            )
        except Exception as e:
            return ExecutionResult(
                ok=False,
                operation="vault.create",
                source="local",
                provider="local_vault",
                error=f"Failed to create file: {str(e)}",
                error_code="INTERNAL_ERROR",
                fetched_at=now
            )

    def write_file(self, user_id: str, params: Optional[Dict[str, Any]] = None) -> ExecutionResult:
        """
        Updates an existing file or creates it if specified.
        Params:
          path (str, required): Target relative file path.
          content (str, required): Text content to write.
          mode (str, default 'replace'): 'replace' or 'append'.
          create_if_missing (bool, default True): Create file if it does not exist.
        """
        params = params or {}
        file_rel = (params.get("path") or "").strip()
        content = params.get("content", "")
        mode = (params.get("mode") or "replace").lower()
        create_if_missing = bool(params.get("create_if_missing", True))
        now = time.time()

        if not file_rel:
            return ExecutionResult(
                ok=False,
                operation="vault.write",
                source="local",
                provider="local_vault",
                error="Parameter 'path' is required for vault.write.",
                error_code="INVALID_PARAMS",
                fetched_at=now
            )

        if mode not in ("replace", "append"):
            return ExecutionResult(
                ok=False,
                operation="vault.write",
                source="local",
                provider="local_vault",
                error=f"Invalid write mode '{mode}'. Supported modes: 'replace', 'append'.",
                error_code="INVALID_PARAMS",
                fetched_at=now
            )

        try:
            target_file = self._resolve_safe_path(file_rel)
        except NexusAgentError as ne:
            return ExecutionResult(
                ok=False,
                operation="vault.write",
                source="local",
                provider="local_vault",
                error=ne.message,
                error_code=ne.code,
                fetched_at=now
            )

        exists = os.path.exists(target_file)
        if not exists and not create_if_missing:
            return ExecutionResult(
                ok=False,
                operation="vault.write",
                source="local",
                provider="local_vault",
                error=f"File '{file_rel}' does not exist and create_if_missing is False.",
                error_code="NOT_FOUND",
                fetched_at=now
            )

        content_bytes = content.encode("utf-8") if isinstance(content, str) else bytes(content)

        try:
            parent_dir = os.path.dirname(target_file)
            if parent_dir:
                os.makedirs(parent_dir, exist_ok=True)

            if mode == "append" and exists:
                with open(target_file, "ab") as f:
                    f.write(content_bytes)
            else:
                # Atomic replace
                temp_path = f"{target_file}.tmp_{int(now * 1000)}"
                with open(temp_path, "wb") as f:
                    f.write(content_bytes)
                os.replace(temp_path, target_file)

            final_size = os.path.getsize(target_file)
            with open(target_file, "rb") as f:
                sha256_hash = hashlib.sha256(f.read()).hexdigest()

            rel_path = self._get_relative_path(target_file)

            return ExecutionResult(
                ok=True,
                operation="vault.write",
                source="local",
                provider="local_vault",
                data={
                    "path": rel_path,
                    "mode": mode,
                    "size_bytes": final_size,
                    "sha256": sha256_hash,
                    "modified_by": user_id,
                    "modified_at": now
                },
                fetched_at=now
            )
        except Exception as e:
            return ExecutionResult(
                ok=False,
                operation="vault.write",
                source="local",
                provider="local_vault",
                error=f"Failed to write file: {str(e)}",
                error_code="INTERNAL_ERROR",
                fetched_at=now
            )

    def rename_item(self, user_id: str, params: Optional[Dict[str, Any]] = None) -> ExecutionResult:
        """
        Renames a file or directory within the agent-visible Vault root.
        Params:
          source_path (str, required): Existing path relative to root.
          target_path (str, required): New relative path or name.
        """
        params = params or {}
        src_rel = (params.get("source_path") or "").strip()
        dst_rel = (params.get("target_path") or params.get("new_name") or "").strip()
        now = time.time()

        if not src_rel or not dst_rel:
            return ExecutionResult(
                ok=False,
                operation="vault.rename",
                source="local",
                provider="local_vault",
                error="Parameters 'source_path' and 'target_path' are required.",
                error_code="INVALID_PARAMS",
                fetched_at=now
            )

        try:
            src_abs = self._resolve_safe_path(src_rel)
            dst_abs = self._resolve_safe_path(dst_rel)
        except NexusAgentError as ne:
            return ExecutionResult(
                ok=False,
                operation="vault.rename",
                source="local",
                provider="local_vault",
                error=ne.message,
                error_code=ne.code,
                fetched_at=now
            )

        if not os.path.exists(src_abs):
            return ExecutionResult(
                ok=False,
                operation="vault.rename",
                source="local",
                provider="local_vault",
                error=f"Source path '{src_rel}' does not exist.",
                error_code="NOT_FOUND",
                fetched_at=now
            )

        if os.path.exists(dst_abs):
            return ExecutionResult(
                ok=False,
                operation="vault.rename",
                source="local",
                provider="local_vault",
                error=f"Target path '{dst_rel}' already exists.",
                error_code="FILE_EXISTS",
                fetched_at=now
            )

        try:
            parent_dir = os.path.dirname(dst_abs)
            if parent_dir:
                os.makedirs(parent_dir, exist_ok=True)
            os.replace(src_abs, dst_abs)
            return ExecutionResult(
                ok=True,
                operation="vault.rename",
                source="local",
                provider="local_vault",
                data={
                    "old_path": self._get_relative_path(src_abs),
                    "new_path": self._get_relative_path(dst_abs),
                    "renamed_at": now
                },
                fetched_at=now
            )
        except Exception as e:
            return ExecutionResult(
                ok=False,
                operation="vault.rename",
                source="local",
                provider="local_vault",
                error=f"Failed to rename: {str(e)}",
                error_code="INTERNAL_ERROR",
                fetched_at=now
            )

    def move_item(self, user_id: str, params: Optional[Dict[str, Any]] = None) -> ExecutionResult:
        """
        Moves a file or directory to a new directory within the agent-visible Vault root.
        Params:
          source_path (str, required): Source relative path.
          destination_path (str, required): Destination relative path.
        """
        params = params or {}
        src_rel = (params.get("source_path") or "").strip()
        dst_rel = (params.get("destination_path") or "").strip()
        now = time.time()

        if not src_rel or not dst_rel:
            return ExecutionResult(
                ok=False,
                operation="vault.move",
                source="local",
                provider="local_vault",
                error="Parameters 'source_path' and 'destination_path' are required.",
                error_code="INVALID_PARAMS",
                fetched_at=now
            )

        try:
            src_abs = self._resolve_safe_path(src_rel)
            dst_abs = self._resolve_safe_path(dst_rel)
        except NexusAgentError as ne:
            return ExecutionResult(
                ok=False,
                operation="vault.move",
                source="local",
                provider="local_vault",
                error=ne.message,
                error_code=ne.code,
                fetched_at=now
            )

        if not os.path.exists(src_abs):
            return ExecutionResult(
                ok=False,
                operation="vault.move",
                source="local",
                provider="local_vault",
                error=f"Source path '{src_rel}' does not exist.",
                error_code="NOT_FOUND",
                fetched_at=now
            )

        try:
            parent_dir = os.path.dirname(dst_abs)
            if parent_dir:
                os.makedirs(parent_dir, exist_ok=True)
            shutil.move(src_abs, dst_abs)
            return ExecutionResult(
                ok=True,
                operation="vault.move",
                source="local",
                provider="local_vault",
                data={
                    "source_path": self._get_relative_path(src_abs),
                    "destination_path": self._get_relative_path(dst_abs),
                    "moved_at": now
                },
                fetched_at=now
            )
        except Exception as e:
            return ExecutionResult(
                ok=False,
                operation="vault.move",
                source="local",
                provider="local_vault",
                error=f"Failed to move: {str(e)}",
                error_code="INTERNAL_ERROR",
                fetched_at=now
            )

    def copy_item(self, user_id: str, params: Optional[Dict[str, Any]] = None) -> ExecutionResult:
        """
        Copies a file or directory within the agent-visible Vault root.
        Params:
          source_path (str, required): Source relative path.
          destination_path (str, required): Destination relative path.
        """
        params = params or {}
        src_rel = (params.get("source_path") or "").strip()
        dst_rel = (params.get("destination_path") or "").strip()
        now = time.time()

        if not src_rel or not dst_rel:
            return ExecutionResult(
                ok=False,
                operation="vault.copy",
                source="local",
                provider="local_vault",
                error="Parameters 'source_path' and 'destination_path' are required.",
                error_code="INVALID_PARAMS",
                fetched_at=now
            )

        try:
            src_abs = self._resolve_safe_path(src_rel)
            dst_abs = self._resolve_safe_path(dst_rel)
        except NexusAgentError as ne:
            return ExecutionResult(
                ok=False,
                operation="vault.copy",
                source="local",
                provider="local_vault",
                error=ne.message,
                error_code=ne.code,
                fetched_at=now
            )

        if not os.path.exists(src_abs):
            return ExecutionResult(
                ok=False,
                operation="vault.copy",
                source="local",
                provider="local_vault",
                error=f"Source path '{src_rel}' does not exist.",
                error_code="NOT_FOUND",
                fetched_at=now
            )

        if os.path.exists(dst_abs):
            return ExecutionResult(
                ok=False,
                operation="vault.copy",
                source="local",
                provider="local_vault",
                error=f"Destination '{dst_rel}' already exists.",
                error_code="FILE_EXISTS",
                fetched_at=now
            )

        try:
            parent_dir = os.path.dirname(dst_abs)
            if parent_dir:
                os.makedirs(parent_dir, exist_ok=True)

            if os.path.isdir(src_abs):
                shutil.copytree(src_abs, dst_abs)
            else:
                shutil.copy2(src_abs, dst_abs)

            return ExecutionResult(
                ok=True,
                operation="vault.copy",
                source="local",
                provider="local_vault",
                data={
                    "source_path": self._get_relative_path(src_abs),
                    "destination_path": self._get_relative_path(dst_abs),
                    "copied_at": now
                },
                fetched_at=now
            )
        except Exception as e:
            return ExecutionResult(
                ok=False,
                operation="vault.copy",
                source="local",
                provider="local_vault",
                error=f"Failed to copy: {str(e)}",
                error_code="INTERNAL_ERROR",
                fetched_at=now
            )

    # --------------------------------------------------------------------------
    # Archive Operations (Phase 3.5)
    # --------------------------------------------------------------------------

    def archive_list(self, user_id: str, params: Optional[Dict[str, Any]] = None) -> ExecutionResult:
        """
        Lists files and metadata within a zip or tar archive in the Vault.
        Params:
          path (str, required): Relative path to archive inside vault.
        """
        import zipfile
        import tarfile

        params = params or {}
        archive_path = (params.get("path") or "").strip()
        now = time.time()

        if not archive_path:
            return ExecutionResult(
                ok=False,
                operation="vault.archive_list",
                source="local",
                provider="local_vault",
                error="Parameter 'path' is required.",
                error_code="INVALID_PARAMS",
                fetched_at=now
            )

        try:
            abs_path = self._resolve_safe_path(archive_path)
        except NexusAgentError as ne:
            return ExecutionResult(
                ok=False,
                operation="vault.archive_list",
                source="local",
                provider="local_vault",
                error=ne.message,
                error_code=ne.code,
                fetched_at=now
            )

        if not os.path.isfile(abs_path):
            return ExecutionResult(
                ok=False,
                operation="vault.archive_list",
                source="local",
                provider="local_vault",
                error=f"Archive '{archive_path}' not found.",
                error_code="NOT_FOUND",
                fetched_at=now
            )

        entries = []
        total_uncompressed_bytes = 0

        try:
            if zipfile.is_zipfile(abs_path):
                with zipfile.ZipFile(abs_path, "r") as zf:
                    for info in zf.infolist():
                        total_uncompressed_bytes += info.file_size
                        entries.append({
                            "name": info.filename,
                            "size_bytes": info.file_size,
                            "compressed_size_bytes": info.compress_size,
                            "is_dir": info.is_dir(),
                            "date_time": f"{info.date_time[0]:04d}-{info.date_time[1]:02d}-{info.date_time[2]:02d} {info.date_time[3]:02d}:{info.date_time[4]:02d}:{info.date_time[5]:02d}"
                        })
            elif tarfile.is_tarfile(abs_path):
                with tarfile.open(abs_path, "r:*") as tf:
                    for member in tf.getmembers():
                        total_uncompressed_bytes += member.size
                        entries.append({
                            "name": member.name,
                            "size_bytes": member.size,
                            "is_dir": member.isdir(),
                            "is_symlink": member.issym() or member.islnk()
                        })
            else:
                return ExecutionResult(
                    ok=False,
                    operation="vault.archive_list",
                    source="local",
                    provider="local_vault",
                    error="Unsupported archive format (expected .zip or .tar.gz).",
                    error_code="UNSUPPORTED_ARCHIVE_FORMAT",
                    fetched_at=now
                )

            return ExecutionResult(
                ok=True,
                operation="vault.archive_list",
                source="local",
                provider="local_vault",
                data={
                    "archive_path": self._get_relative_path(abs_path),
                    "total_entries": len(entries),
                    "total_uncompressed_bytes": total_uncompressed_bytes,
                    "entries": entries[:200]
                },
                fetched_at=now
            )
        except Exception as e:
            return ExecutionResult(
                ok=False,
                operation="vault.archive_list",
                source="local",
                provider="local_vault",
                error=f"Failed to read archive: {str(e)}",
                error_code="ARCHIVE_READ_ERROR",
                fetched_at=now
            )

    def archive_extract(self, user_id: str, params: Optional[Dict[str, Any]] = None) -> ExecutionResult:
        """
        Safely extracts an archive into a destination directory within the Vault.
        Enforces strict Zip Slip protection, max file count (500), and max uncompressed size (100 MB).
        Params:
          path (str, required): Archive relative path in vault.
          destination_dir (str, required): Target directory in vault.
          max_files (int, default 500): Maximum files allowed to extract.
          max_total_bytes (int, default 104857600): Maximum uncompressed bytes allowed.
        """
        import zipfile
        import tarfile

        params = params or {}
        archive_path = (params.get("path") or "").strip()
        dest_rel = (params.get("destination_dir") or "").strip()
        max_files = int(params.get("max_files", 500))
        max_total_bytes = int(params.get("max_total_bytes", 104857600))  # 100 MB
        now = time.time()

        if not archive_path or not dest_rel:
            return ExecutionResult(
                ok=False,
                operation="vault.archive_extract",
                source="local",
                provider="local_vault",
                error="Parameters 'path' and 'destination_dir' are required.",
                error_code="INVALID_PARAMS",
                fetched_at=now
            )

        try:
            abs_archive = self._resolve_safe_path(archive_path)
            abs_dest = self._resolve_safe_path(dest_rel)
        except NexusAgentError as ne:
            return ExecutionResult(
                ok=False,
                operation="vault.archive_extract",
                source="local",
                provider="local_vault",
                error=ne.message,
                error_code=ne.code,
                fetched_at=now
            )

        if not os.path.isfile(abs_archive):
            return ExecutionResult(
                ok=False,
                operation="vault.archive_extract",
                source="local",
                provider="local_vault",
                error=f"Archive '{archive_path}' not found.",
                error_code="NOT_FOUND",
                fetched_at=now
            )

        os.makedirs(abs_dest, exist_ok=True)
        extracted_files = []
        total_extracted_bytes = 0

        try:
            if zipfile.is_zipfile(abs_archive):
                with zipfile.ZipFile(abs_archive, "r") as zf:
                    infolist = zf.infolist()
                    if len(infolist) > max_files:
                        return ExecutionResult(
                            ok=False,
                            operation="vault.archive_extract",
                            source="local",
                            provider="local_vault",
                            error=f"Archive contains {len(infolist)} files, exceeding limit of {max_files}.",
                            error_code="ARCHIVE_LIMIT_EXCEEDED",
                            fetched_at=now
                        )

                    for info in infolist:
                        # 1. Zip Slip / Traversal check
                        clean_name = os.path.normpath(info.filename.replace("\\", "/"))
                        if clean_name.startswith("..") or os.path.isabs(clean_name):
                            raise VaultAccessError(f"Zip Slip attack detected in member '{info.filename}'.")

                        # 2. Symlink / Device check
                        is_symlink = (info.external_attr >> 16) & 0o120000 == 0o120000
                        if is_symlink:
                            logger.warning(f"Skipping symlink entry in zip: {info.filename}")
                            continue

                        # 3. Decompression size check
                        total_extracted_bytes += info.file_size
                        if total_extracted_bytes > max_total_bytes:
                            raise ValueError(f"Extracted size exceeds safety limit ({max_total_bytes} bytes).")

                        target_file = os.path.join(abs_dest, clean_name)
                        # Verify target is strictly within abs_dest
                        if not os.path.realpath(target_file).startswith(os.path.realpath(abs_dest)):
                            raise VaultAccessError(f"Member '{info.filename}' escapes destination directory.")

                        if info.is_dir():
                            os.makedirs(target_file, exist_ok=True)
                        else:
                            os.makedirs(os.path.dirname(target_file), exist_ok=True)
                            with zf.open(info) as src, open(target_file, "wb") as dst:
                                shutil.copyfileobj(src, dst)
                            extracted_files.append(self._get_relative_path(target_file))

            elif tarfile.is_tarfile(abs_archive):
                with tarfile.open(abs_archive, "r:*") as tf:
                    members = tf.getmembers()
                    if len(members) > max_files:
                        return ExecutionResult(
                            ok=False,
                            operation="vault.archive_extract",
                            source="local",
                            provider="local_vault",
                            error=f"Archive contains {len(members)} files, exceeding limit of {max_files}.",
                            error_code="ARCHIVE_LIMIT_EXCEEDED",
                            fetched_at=now
                        )

                    for member in members:
                        clean_name = os.path.normpath(member.name.replace("\\", "/"))
                        if clean_name.startswith("..") or os.path.isabs(clean_name):
                            raise VaultAccessError(f"Tar traversal attack detected in member '{member.name}'.")

                        if member.issym() or member.islnk() or member.ischr() or member.isblk() or member.isfifo():
                            logger.warning(f"Skipping special/symlink member in tar: {member.name}")
                            continue

                        total_extracted_bytes += member.size
                        if total_extracted_bytes > max_total_bytes:
                            raise ValueError(f"Extracted size exceeds safety limit ({max_total_bytes} bytes).")

                        target_file = os.path.join(abs_dest, clean_name)
                        if not os.path.realpath(target_file).startswith(os.path.realpath(abs_dest)):
                            raise VaultAccessError(f"Member '{member.name}' escapes destination directory.")

                        if member.isdir():
                            os.makedirs(target_file, exist_ok=True)
                        else:
                            os.makedirs(os.path.dirname(target_file), exist_ok=True)
                            f = tf.extractfile(member)
                            if f:
                                with open(target_file, "wb") as dst:
                                    shutil.copyfileobj(f, dst)
                                extracted_files.append(self._get_relative_path(target_file))
            else:
                return ExecutionResult(
                    ok=False,
                    operation="vault.archive_extract",
                    source="local",
                    provider="local_vault",
                    error="Unsupported archive format.",
                    error_code="UNSUPPORTED_ARCHIVE_FORMAT",
                    fetched_at=now
                )

            return ExecutionResult(
                ok=True,
                operation="vault.archive_extract",
                source="local",
                provider="local_vault",
                data={
                    "archive_path": self._get_relative_path(abs_archive),
                    "destination_dir": self._get_relative_path(abs_dest),
                    "files_extracted_count": len(extracted_files),
                    "total_bytes_extracted": total_extracted_bytes,
                    "extracted_files": extracted_files[:100],
                    "extracted_at": now
                },
                fetched_at=now
            )
        except Exception as e:
            return ExecutionResult(
                ok=False,
                operation="vault.archive_extract",
                source="local",
                provider="local_vault",
                error=f"Archive extraction failed: {str(e)}",
                error_code="ARCHIVE_EXTRACTION_ERROR",
                fetched_at=now
            )

    # --------------------------------------------------------------------------
    # Document Extraction & Creation (Phase 3.5)
    # --------------------------------------------------------------------------

    def document_extract(self, user_id: str, params: Optional[Dict[str, Any]] = None) -> ExecutionResult:
        """
        Extracts structured text from academic documents (.pdf, .txt, .md).
        Supports bounded page ranges (start_page, end_page) and character pagination.
        Params:
          path (str, required): Relative path inside vault.
          start_page (int, optional): 1-indexed start page for PDF (default 1).
          end_page (int, optional): 1-indexed end page for PDF (default None / all).
          max_chars (int, default 4000, max 20000): Maximum characters to extract.
          offset (int, default 0): Character offset for plain text.
        """
        params = params or {}
        file_path = (params.get("path") or "").strip()
        start_page = max(1, int(params.get("start_page", 1)))
        end_page = int(params.get("end_page")) if params.get("end_page") is not None else None
        max_chars = min(20000, max(100, int(params.get("max_chars", 4000))))
        offset = max(0, int(params.get("offset", 0)))
        now = time.time()

        if not file_path:
            return ExecutionResult(
                ok=False,
                operation="document.extract",
                source="local",
                provider="local_vault",
                error="Parameter 'path' is required.",
                error_code="INVALID_PARAMS",
                fetched_at=now
            )

        try:
            abs_path = self._resolve_safe_path(file_path)
        except NexusAgentError as ne:
            return ExecutionResult(
                ok=False,
                operation="document.extract",
                source="local",
                provider="local_vault",
                error=ne.message,
                error_code=ne.code,
                fetched_at=now
            )

        if not os.path.isfile(abs_path):
            return ExecutionResult(
                ok=False,
                operation="document.extract",
                source="local",
                provider="local_vault",
                error=f"Document '{file_path}' not found.",
                error_code="NOT_FOUND",
                fetched_at=now
            )

        ext = os.path.splitext(abs_path)[1].lower()
        
        try:
            if ext == ".pdf":
                from pypdf import PdfReader
                reader = PdfReader(abs_path)
                total_pages = len(reader.pages)
                
                target_end = min(total_pages, end_page) if end_page else total_pages
                page_texts = []
                accumulated_chars = 0
                
                for idx in range(start_page - 1, target_end):
                    page = reader.pages[idx]
                    p_text = page.extract_text() or ""
                    header = f"\n--- Page {idx + 1} ---\n"
                    page_texts.append(header + p_text)
                    accumulated_chars += len(header) + len(p_text)
                    if accumulated_chars >= max_chars:
                        break

                full_text = "".join(page_texts)[:max_chars]
                return ExecutionResult(
                    ok=True,
                    operation="document.extract",
                    source="local",
                    provider="local_vault",
                    data={
                        "path": self._get_relative_path(abs_path),
                        "content_type": "extracted_pdf_text",
                        "total_pages": total_pages,
                        "extracted_pages": [start_page, min(start_page + len(page_texts) - 1, target_end)],
                        "character_count": len(full_text),
                        "text": full_text
                    },
                    fetched_at=now
                )
            else:
                # Text or Markdown
                with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
                    if offset > 0:
                        f.seek(offset)
                    text = f.read(max_chars)

                return ExecutionResult(
                    ok=True,
                    operation="document.extract",
                    source="local",
                    provider="local_vault",
                    data={
                        "path": self._get_relative_path(abs_path),
                        "content_type": "text/markdown" if ext == ".md" else "text/plain",
                        "character_count": len(text),
                        "offset": offset,
                        "text": text
                    },
                    fetched_at=now
                )
        except Exception as e:
            return ExecutionResult(
                ok=False,
                operation="document.extract",
                source="local",
                provider="local_vault",
                error=f"Document extraction failed: {str(e)}",
                error_code="DOCUMENT_EXTRACTION_ERROR",
                fetched_at=now
            )

    def document_create(self, user_id: str, params: Optional[Dict[str, Any]] = None) -> ExecutionResult:
        """
        Creates an academic document (.md, .txt, or .pdf via ReportLab) inside the Vault.
        Params:
          path (str, required): Target relative path in vault (e.g. 'Assignments/summary.pdf').
          content (str, required): Text/markdown content to write.
          format (str, optional): 'txt', 'md', 'pdf' (inferred from path extension if omitted).
          title (str, optional): Document title for PDF header.
        """
        params = params or {}
        dest_path = (params.get("path") or "").strip()
        content = params.get("content", "")
        doc_format = (params.get("format") or "").strip().lower()
        title = params.get("title") or os.path.splitext(os.path.basename(dest_path))[0]
        now = time.time()

        if not dest_path or content is None:
            return ExecutionResult(
                ok=False,
                operation="document.create",
                source="local",
                provider="local_vault",
                error="Parameters 'path' and 'content' are required.",
                error_code="INVALID_PARAMS",
                fetched_at=now
            )

        try:
            abs_path = self._resolve_safe_path(dest_path)
        except NexusAgentError as ne:
            return ExecutionResult(
                ok=False,
                operation="document.create",
                source="local",
                provider="local_vault",
                error=ne.message,
                error_code=ne.code,
                fetched_at=now
            )

        if not doc_format:
            ext = os.path.splitext(abs_path)[1].lower().lstrip(".")
            doc_format = ext if ext in ("txt", "md", "pdf") else "md"

        os.makedirs(os.path.dirname(abs_path), exist_ok=True)

        try:
            if doc_format == "pdf":
                from reportlab.lib.pagesizes import letter
                from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
                from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
                from reportlab.lib import colors

                doc = SimpleDocTemplate(
                    abs_path,
                    pagesize=letter,
                    rightMargin=54,
                    leftMargin=54,
                    topMargin=54,
                    bottomMargin=54
                )
                styles = getSampleStyleSheet()
                title_style = ParagraphStyle(
                    'DocTitle',
                    parent=styles['Heading1'],
                    fontSize=18,
                    leading=22,
                    textColor=colors.HexColor("#1a365d"),
                    spaceAfter=12
                )
                body_style = ParagraphStyle(
                    'DocBody',
                    parent=styles['Normal'],
                    fontSize=10,
                    leading=14,
                    textColor=colors.HexColor("#2d3748"),
                    spaceAfter=8
                )

                story = [
                    Paragraph(title, title_style),
                    Spacer(1, 10)
                ]

                # Convert markdown lines / text lines to paragraphs
                for line in content.split("\n"):
                    clean_l = line.strip()
                    if not clean_l:
                        story.append(Spacer(1, 6))
                        continue
                    # Safe HTML entity escaping for reportlab XML
                    safe_l = clean_l.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                    if safe_l.startswith("# "):
                        story.append(Paragraph(safe_l[2:], styles['Heading1']))
                    elif safe_l.startswith("## "):
                        story.append(Paragraph(safe_l[3:], styles['Heading2']))
                    elif safe_l.startswith("### "):
                        story.append(Paragraph(safe_l[4:], styles['Heading3']))
                    elif safe_l.startswith("- ") or safe_l.startswith("* "):
                        story.append(Paragraph(f"&bull; {safe_l[2:]}", body_style))
                    else:
                        story.append(Paragraph(safe_l, body_style))

                doc.build(story)
            else:
                # Plain text or Markdown
                with open(abs_path, "w", encoding="utf-8") as f:
                    f.write(content)

            file_size = os.path.getsize(abs_path)
            return ExecutionResult(
                ok=True,
                operation="document.create",
                source="local",
                provider="local_vault",
                data={
                    "path": self._get_relative_path(abs_path),
                    "format": doc_format,
                    "size_bytes": file_size,
                    "created_at": now
                },
                fetched_at=now
            )
        except Exception as e:
            return ExecutionResult(
                ok=False,
                operation="document.create",
                source="local",
                provider="local_vault",
                error=f"Document creation failed: {str(e)}",
                error_code="DOCUMENT_CREATION_ERROR",
                fetched_at=now
            )


