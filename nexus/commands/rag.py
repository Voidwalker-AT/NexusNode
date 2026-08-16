"""
NexusNode CLI — Authoritative SQLite FTS5 RAG Command
Communicates with /api/rag/diagnostics, /api/rag/sources, /api/rag/index, and /api/rag/compact.
"""

from .. import output
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
        output.print_error(f"Failed to fetch RAG diagnostics (HTTP {status_code})")
        return 1

    if as_json or getattr(args, "json", False):
        output.print_json(resp)
        return 0

    print("\n" + "=" * 55)
    print("NEXUSNODE SQLITE FTS5 RAG STATUS")
    print("=" * 55)
    print(f"  Index Status:        {resp.get('status', 'UNKNOWN').upper()}")
    print(f"  Indexed Documents:   {resp.get('indexed_documents_count', 0)}")
    print(f"  Total Chunks:        {resp.get('chunks_count', 0)}")
    print(f"  Index Size on Disk:  {output.format_bytes(resp.get('index_size_bytes', 0))}")
    print(f"  Algorithm:           {resp.get('algorithm', 'BM25 + FTS5 Inverted Index')}")
    print(f"  Last Reindex Time:   {output.format_timestamp(resp.get('last_indexed_at'))}")
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
    if status_code != 200 or not isinstance(resp, dict):
        output.print_error(f"Search failed (HTTP {status_code})")
        return 1

    if as_json or getattr(args, "json", False):
        output.print_json(resp)
        return 0

    results = resp.get("results", [])
    if not results:
        print(f"\nNo indexed documents matched query '{query}'.\n")
        return 0

    print(f"\n--- RAG SEARCH RESULTS for '{query}' ({len(results)} matches) ---")
    for i, r in enumerate(results, 1):
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
        output.print_error(f"Failed to list RAG sources (HTTP {status_code})")
        return 1

    if as_json or getattr(args, "json", False):
        output.print_json(resp)
        return 0

    sources = resp.get("sources", [])
    if not sources:
        print("\nNo documents indexed in RAG.\n")
        return 0

    headers = ["DOCUMENT", "CHUNKS", "INDEXED AT"]
    rows = []
    for s in sources:
        rows.append([
            s.get("filename", "N/A"),
            s.get("chunk_count", 0),
            output.format_timestamp(s.get("indexed_at"))
        ])

    print(f"\n--- INDEXED RAG SOURCES ({len(sources)} files) ---")
    output.print_table(headers, rows)
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
    if status_code != 200:
        err = resp.get("error", f"HTTP {status_code}") if isinstance(resp, dict) else str(resp)
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

    if status_code == 200:
        if as_json or getattr(args, "json", False):
            output.print_json(resp)
        else:
            output.print_success("RAG database compacted successfully.")
        return 0
    else:
        err = resp.get("error", f"HTTP {status_code}") if isinstance(resp, dict) else str(resp)
        output.print_error(f"RAG compaction failed: {err}")
        return 1
