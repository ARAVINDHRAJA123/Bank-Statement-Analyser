from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


def send_message(proc: subprocess.Popen[bytes], message: dict[str, Any]) -> dict[str, Any]:
    body = json.dumps(message).encode("utf-8")
    proc.stdin.write(f"Content-Length: {len(body)}\r\n\r\n".encode("utf-8"))
    proc.stdin.write(body)
    proc.stdin.flush()

    header = b""
    while b"\r\n\r\n" not in header:
        chunk = proc.stdout.read(1)
        if not chunk:
            stderr = proc.stderr.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"MCP server closed unexpectedly.\n{stderr}")
        header += chunk

    raw_headers, _, remainder = header.partition(b"\r\n\r\n")
    content_length = None
    for line in raw_headers.decode("utf-8").split("\r\n"):
        if line.lower().startswith("content-length:"):
            content_length = int(line.split(":", 1)[1].strip())
            break
    if content_length is None:
        raise RuntimeError("Missing Content-Length in MCP response.")

    body = remainder
    if len(body) < content_length:
        body += proc.stdout.read(content_length - len(body))
    return json.loads(body.decode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-test the local bank MCP server over stdio.")
    parser.add_argument(
        "--repo-root",
        default=Path(__file__).resolve().parents[1],
        type=Path,
        help="Path to the Bank-Statement-Analyser repo root.",
    )
    parser.add_argument(
        "--pdf-path",
        help="Optional PDF path to validate analyse_pdf. Must fall under BANK_MCP_ALLOWED_INPUT_DIRS.",
    )
    args = parser.parse_args()

    server_path = args.repo_root / "mcp_server.py"
    if not server_path.is_file():
        print(f"ERROR: MCP server not found at {server_path}", file=sys.stderr)
        return 1

    proc = subprocess.Popen(
        [sys.executable, str(server_path)],
        cwd=args.repo_root,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    try:
        initialize = send_message(proc, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        tools = send_message(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        status = send_message(
            proc,
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "project_status", "arguments": {}},
            },
        )

        print("== initialize ==")
        print(json.dumps(initialize, indent=2))
        print("\n== tools/list ==")
        print(json.dumps(tools, indent=2))
        print("\n== tools/call project_status ==")
        print(json.dumps(status, indent=2))

        if args.pdf_path:
            analyse = send_message(
                proc,
                {
                    "jsonrpc": "2.0",
                    "id": 4,
                    "method": "tools/call",
                    "params": {"name": "analyse_pdf", "arguments": {"pdf_path": args.pdf_path}},
                },
            )
            print("\n== tools/call analyse_pdf ==")
            print(json.dumps(analyse, indent=2))

    finally:
        proc.terminate()
        proc.wait(timeout=5)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
