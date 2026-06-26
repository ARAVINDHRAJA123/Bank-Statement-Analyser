from __future__ import annotations

from pathlib import Path

from mcp.server.fastmcp import FastMCP

from bank_mcp_tools import ToolContext, call_tool

mcp = FastMCP("bank-statement-mcp")
_ctx = ToolContext.from_repo_root(Path(__file__).resolve().parent)


@mcp.tool()
def project_status() -> dict:
    """Return local project and environment status for planning agent actions."""
    return call_tool(_ctx, "project_status", {})


@mcp.tool()
def analyse_pdf(pdf_path: str) -> dict:
    """Generate an Excel report from a text-based HDFC bank-statement PDF.
    Only reads PDFs inside the configured allowlist directories."""
    return call_tool(_ctx, "analyse_pdf", {"pdf_path": pdf_path})


@mcp.tool()
def ask_warehouse(question: str, model: str = None) -> dict:
    """Ask a plain-English analytics question over the BigQuery marts using
    the existing read-only text-to-SQL guardrails."""
    args = {"question": question}
    if model:
        args["model"] = model
    return call_tool(_ctx, "ask_warehouse", args)


if __name__ == "__main__":
    mcp.run()
