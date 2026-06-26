from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from Bank_Statement_Analyser import analyse


DEFAULT_OUTPUT_DIR = Path(os.environ.get("BANK_MCP_OUTPUT_DIR", "reports/mcp")).resolve()
DEFAULT_ALLOWED_INPUT_DIRS = tuple(
    Path(p).resolve()
    for p in os.environ.get("BANK_MCP_ALLOWED_INPUT_DIRS", str(Path.cwd())).split(os.pathsep)
    if p.strip()
)
MAX_PDF_MB = int(os.environ.get("BANK_MCP_MAX_PDF_MB", "20"))
ENABLE_BQ_LOAD = os.environ.get("BANK_MCP_ENABLE_BQ_LOAD", "").lower() in {"1", "true", "yes"}


class ToolError(RuntimeError):
    """Raised for predictable, user-facing tool failures."""


@dataclass(frozen=True)
class ToolContext:
    repo_root: Path
    output_dir: Path = DEFAULT_OUTPUT_DIR
    allowed_input_dirs: tuple[Path, ...] = DEFAULT_ALLOWED_INPUT_DIRS
    max_pdf_mb: int = MAX_PDF_MB
    enable_bq_load: bool = ENABLE_BQ_LOAD

    @classmethod
    def from_repo_root(cls, repo_root: str | Path) -> "ToolContext":
        root = Path(repo_root).resolve()
        output_dir = Path(os.environ.get("BANK_MCP_OUTPUT_DIR", root / "reports" / "mcp")).resolve()
        allowed = os.environ.get("BANK_MCP_ALLOWED_INPUT_DIRS")
        if allowed:
            allowed_dirs = tuple(Path(p).resolve() for p in allowed.split(os.pathsep) if p.strip())
        else:
            allowed_dirs = (root,)
        return cls(
            repo_root=root,
            output_dir=output_dir,
            allowed_input_dirs=allowed_dirs,
            max_pdf_mb=int(os.environ.get("BANK_MCP_MAX_PDF_MB", "20")),
            enable_bq_load=os.environ.get("BANK_MCP_ENABLE_BQ_LOAD", "").lower() in {"1", "true", "yes"},
        )


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _validate_pdf_path(ctx: ToolContext, pdf_path: str) -> Path:
    candidate = Path(pdf_path).expanduser().resolve()
    if candidate.suffix.lower() != ".pdf":
        raise ToolError("Only .pdf inputs are allowed.")
    if not candidate.is_file():
        raise ToolError(f"PDF not found: {candidate}")
    if not any(_is_relative_to(candidate, allowed) for allowed in ctx.allowed_input_dirs):
        allowed = ", ".join(str(p) for p in ctx.allowed_input_dirs)
        raise ToolError(f"PDF path is outside the allowed roots: {allowed}")
    size_mb = candidate.stat().st_size / (1024 * 1024)
    if size_mb > ctx.max_pdf_mb:
        raise ToolError(f"PDF is too large ({size_mb:.1f} MB). Limit is {ctx.max_pdf_mb} MB.")
    return candidate


def tool_definitions(ctx: ToolContext) -> list[dict[str, Any]]:
    definitions: list[dict[str, Any]] = [
        {
            "name": "project_status",
            "description": "Return local project and environment status for planning agent actions.",
            "inputSchema": {"type": "object", "properties": {}},
        },
        {
            "name": "analyse_pdf",
            "description": (
                "Generate an Excel report from a text-based HDFC bank-statement PDF. "
                "Only reads PDFs inside the configured allowlist directories."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "pdf_path": {
                        "type": "string",
                        "description": "Absolute or repo-relative path to a PDF inside the allowed roots.",
                    }
                },
                "required": ["pdf_path"],
            },
        },
        {
            "name": "ask_warehouse",
            "description": (
                "Ask a plain-English analytics question over the BigQuery marts using the existing "
                "read-only text-to-SQL guardrails."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                    "model": {"type": "string"},
                },
                "required": ["question"],
            },
        },
    ]
    if ctx.enable_bq_load:
        definitions.append(
            {
                "name": "load_pdf_to_bigquery",
                "description": (
                    "Parse a PDF and append rows into raw.bank_transactions. Disabled by default "
                    "because it writes to BigQuery."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {"pdf_path": {"type": "string"}},
                    "required": ["pdf_path"],
                },
            }
        )
    return definitions


def project_status(ctx: ToolContext) -> dict[str, Any]:
    llm_provider = "none"
    if os.environ.get("ANTHROPIC_API_KEY"):
        llm_provider = "anthropic"
    elif os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"):
        llm_provider = "gemini"

    return {
        "repo_root": str(ctx.repo_root),
        "allowed_input_dirs": [str(p) for p in ctx.allowed_input_dirs],
        "output_dir": str(ctx.output_dir),
        "bq_load_enabled": ctx.enable_bq_load,
        "gcp_project": os.environ.get("GCP_PROJECT"),
        "bq_location": os.environ.get("BQ_LOCATION"),
        "llm_provider": llm_provider,
        "reports_dir_exists": ctx.output_dir.exists(),
    }


def analyse_pdf(ctx: ToolContext, pdf_path: str) -> dict[str, Any]:
    pdf = _validate_pdf_path(ctx, pdf_path)
    ctx.output_dir.mkdir(parents=True, exist_ok=True)
    report_path = ctx.output_dir / f"{pdf.stem}_report.xlsx"
    stats = analyse(str(pdf), str(report_path))
    return {
        "pdf_path": str(pdf),
        "report_path": str(report_path),
        "stats": stats,
    }


def ask_warehouse(question: str, model: str | None = None) -> dict[str, Any]:
    from ai.ask_statement import ask

    result = ask(question, model=model, return_sql=True)
    return {
        "question": question,
        "answer": result["answer"],
        "sql": result["sql"],
    }


def load_pdf_to_bigquery(ctx: ToolContext, pdf_path: str) -> dict[str, Any]:
    if not ctx.enable_bq_load:
        raise ToolError("BigQuery load is disabled. Set BANK_MCP_ENABLE_BQ_LOAD=true to enable it.")

    pdf = _validate_pdf_path(ctx, pdf_path)

    from google.cloud import bigquery
    from load_to_bigquery import DATASET, LOCATION, PROJECT, SCHEMA, TABLE, to_bq_rows
    from Bank_Statement_Analyser import clean_and_enrich, extract_transactions

    if not PROJECT:
        raise ToolError("GCP_PROJECT is not set.")

    rows = clean_and_enrich(extract_transactions(str(pdf)))
    if not rows:
        raise ToolError("No transactions found. Is the PDF text-based (not scanned)?")

    client = bigquery.Client(project=PROJECT, location=LOCATION)
    table_id = f"{PROJECT}.{DATASET}.{TABLE}"
    dataset = bigquery.Dataset(f"{PROJECT}.{DATASET}")
    dataset.location = LOCATION
    client.create_dataset(dataset, exists_ok=True)

    job_config = bigquery.LoadJobConfig(
        schema=SCHEMA,
        write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
    )
    job = client.load_table_from_json(to_bq_rows(rows), table_id, job_config=job_config)
    job.result()
    table = client.get_table(table_id)
    return {
        "pdf_path": str(pdf),
        "loaded_rows": len(rows),
        "table_id": table_id,
        "table_total_rows": table.num_rows,
    }


def call_tool(ctx: ToolContext, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if name == "project_status":
        return project_status(ctx)
    if name == "analyse_pdf":
        return analyse_pdf(ctx, arguments["pdf_path"])
    if name == "ask_warehouse":
        return ask_warehouse(arguments["question"], arguments.get("model"))
    if name == "load_pdf_to_bigquery":
        return load_pdf_to_bigquery(ctx, arguments["pdf_path"])
    raise ToolError(f"Unknown tool: {name}")


def format_tool_result(payload: dict[str, Any]) -> list[dict[str, str]]:
    return [{"type": "text", "text": json.dumps(payload, indent=2, default=str)}]
