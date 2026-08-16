"""
NexusNode CLI — Authoritative SQLite FTS5 RAG Command
Communicates with /api/rag/diagnostics, /api/rag/sources, /api/rag/index, and /api/rag/compact.
"""

from .. import output
from .. import normalize
from ..client import NexusClient, NexusConnectionError


def cmd_rag(client: NexusClient, args, as_json: bool = False) -> int:
    """Dispatcher for 'nexus rag' subcommands."""
    subaction = getattr(args, "rag_action", None) or "status"

    if subaction == "status" or subaction == "diagnostics":
        return cmd_rag_status(client, args, as_json)
    elif subaction == "search":
        return cmd_rag_search(client, args, as_json)
    elif subaction == "sources":
        return cmd_rag_sources(client, args, as_json)
    elif subaction == "index":
        return cmd_rag_index(client, args, as_json)
    elif subaction == "compact":
        return cmd_rag_compact(client, args, as_json)
    else:
        output.print_error(f"Unknown RAG subcommand '{subaction}'. Type 'nexus rag --help'.")
        return 1


def cmd_rag_status(client: NexusClient, args, as_json: bool = False) -> int:
    try:
        status_code, resp = client.get("/api/rag/diagnostics")
    except NexusConnectionError as e:
        output.print_error(str(e))
        return 1

    if status_code == 403:
        output.print_error("Permission denied: your account lacks 'can_use_rag' privilege.")
        return 1
    if status_code != 200 or not isinstance(resp, dict):
        err = resp.get("message", resp.get("error", f"HTTP {status_code}")) if isinstance(resp, dict) else str(resp)
        output.print_error(f"Failed to fetch RAG diagnostics ({err})")
        return 1

    if as_json or getattr(args, "json", False):
        output.print_json(resp)
        return 0

    norm = normalize.normalize_rag(resp)
    db_size_kb = norm.get("database_size_kb")
    size_str = f"{db_size_kb:.1f} KB" if isinstance(db_size_kb, (int, float)) else "UNAVAILABLE"
    doc_cnt = norm.get("document_count")
    doc_str = str(doc_cnt) if doc_cnt is not None else "UNAVAILABLE"
    chunk_cnt = norm.get("chunk_count")
    chunk_str = str(chunk_cnt) if chunk_cnt is not None else "UNAVAILABLE"

    print("\n" + "=" * 55)
    print("NEXUSNODE SQLITE FTS5 RAG STATUS")
    print("=" * 55)
    print(f"  Index Status:        {norm.get('state', 'READY').upper()}")
    print(f"  Indexed Documents:   {doc_str}")
    print(f"  Total Chunks:        {chunk_str}")
    print(f"  Index Size on Disk:  {size_str}")
    print(f"  Algorithm:           {norm.get('backend', 'SQLite FTS5 (BM25 Ranking)')}")
    print(f"  Last Reindex Time:   {norm.get('last_rebuild_time', 'Never')}")
    print("=" * 55 + "\n")
    return 0


def cmd_rag_search(client: NexusClient, args, as_json: bool = False) -> int:
    query = getattr(args, "query", None)
    if not query:
        try:
            query = input("Search Query: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nCancelled.")
            return 0

    if not query:
        output.print_error("Query cannot be empty.")
        return 1

    try:
        status_code, resp = client.post("/api/rag/sources", data={"query": query, "limit": 10})
    except NexusConnectionError as e:
        output.print_error(str(e))
        return 1

    if status_code == 403:
        output.print_error("Permission denied: your account lacks 'can_use_rag' privilege.")
        return 1
    if status_code != 200:
        err = resp.get("message", resp.get("error", f"HTTP {status_code}")) if isinstance(resp, dict) else str(resp)
        output.print_error(f"Search failed ({err})")
        return 1

    if as_json or getattr(args, "json", False):
        output.print_json(resp)
        return 0

    results = normalize.normalize_list(resp, "results")
    if not results:
        print(f"\nNo indexed documents matched query '{query}'.\n")
        return 0

    print(f"\n--- RAG SEARCH RESULTS for '{query}' ({len(results)} matches) ---")
    for i, r in enumerate(results, 1):
        if not isinstance(r, dict):
            continue
        score = r.get("score", 0.0)
        source = r.get("source_file") or r.get("document", "Unknown")
        snippet = r.get("snippet") or r.get("text", "")
        print(f"\n[{i}] {source} (Score: {score:.2f})")
        print(f"    {snippet[:240].strip()}...")
    print()
    return 0


def cmd_rag_sources(client: NexusClient, args, as_json: bool = False) -> int:
    try:
        status_code, resp = client.get("/api/rag/sources")
    except NexusConnectionError as e:
        output.print_error(str(e))
        return 1

    if status_code != 200 or not isinstance(resp, dict):
        err = resp.get("message", resp.get("error", f"HTTP {status_code}")) if isinstance(resp, dict) else str(resp)
        output.print_error(f"Failed to list RAG sources ({err})")
        return 1

    if as_json or getattr(args, "json", False):
        output.print_json(resp)
        return 0

    sources = resp.get("sources", [])
    extensions = resp.get("supported_extensions", [])

    print(f"\n--- CONFIGURED RAG SOURCE FOLDERS ({len(sources)} sources) ---")
    if sources:
        for s in sources:
            print(f"  • {s}")
    else:
        print("  (None configured)")

    if extensions:
        print(f"\nSupported File Types: {', '.join(extensions)}")
    print()
    return 0


def cmd_rag_index(client: NexusClient, args, as_json: bool = False) -> int:
    print("Triggering background RAG index rebuild...")
    try:
        status_code, resp = client.post("/api/rag/index")
    except NexusConnectionError as e:
        output.print_error(str(e))
        return 1

    if status_code == 403:
        output.print_error("Permission denied: your account lacks 'can_use_rag' privilege.")
        return 1
    if status_code not in [200, 201, 202]:
        err = resp.get("error", resp.get("message", f"HTTP {status_code}")) if isinstance(resp, dict) else str(resp)
        output.print_error(f"Indexing trigger failed: {err}")
        return 1

    if as_json or getattr(args, "json", False):
        output.print_json(resp)
    else:
        output.print_success("RAG reindexing task initiated on server.")
    return 0


def cmd_rag_compact(client: NexusClient, args, as_json: bool = False) -> int:
    try:
        status_code, resp = client.post("/api/rag/compact")
    except NexusConnectionError as e:
        output.print_error(str(e))
        return 1

    if status_code in [200, 201]:
        if as_json or getattr(args, "json", False):
            output.print_json(resp)
        else:
            output.print_success("RAG database compacted successfully.")
        return 0
    else:
        err = resp.get("error", resp.get("message", f"HTTP {status_code}")) if isinstance(resp, dict) else str(resp)
        output.print_error(f"RAG compaction failed: {err}")
        return 1
