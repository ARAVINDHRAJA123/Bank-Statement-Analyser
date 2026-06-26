from __future__ import annotations

import json
from pathlib import Path

import pytest

from bank_mcp_tools import ToolContext, ToolError, call_tool, format_tool_result, tool_definitions


@pytest.fixture()
def ctx(tmp_path: Path) -> ToolContext:
    input_dir = tmp_path / "inputs"
    output_dir = tmp_path / "outputs"
    input_dir.mkdir()
    return ToolContext(
        repo_root=tmp_path,
        output_dir=output_dir,
        allowed_input_dirs=(input_dir,),
        max_pdf_mb=1,
        enable_bq_load=False,
    )


def test_project_status_reports_safe_defaults(ctx: ToolContext) -> None:
    result = call_tool(ctx, "project_status", {})
    assert result["bq_load_enabled"] is False
    assert result["allowed_input_dirs"] == [str(ctx.allowed_input_dirs[0])]


def test_analyse_pdf_rejects_non_pdf(ctx: ToolContext) -> None:
    txt_file = ctx.allowed_input_dirs[0] / "notes.txt"
    txt_file.write_text("hello", encoding="utf-8")

    with pytest.raises(ToolError, match="Only .pdf inputs are allowed"):
        call_tool(ctx, "analyse_pdf", {"pdf_path": str(txt_file)})


def test_analyse_pdf_rejects_outside_allowed_roots(ctx: ToolContext, tmp_path: Path) -> None:
    pdf = tmp_path / "elsewhere.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")

    with pytest.raises(ToolError, match="outside the allowed roots"):
        call_tool(ctx, "analyse_pdf", {"pdf_path": str(pdf)})


def test_format_tool_result_is_json_text() -> None:
    payload = {"hello": "world"}
    result = format_tool_result(payload)
    assert result == [{"type": "text", "text": json.dumps(payload, indent=2)}]


def test_tools_list_exposes_only_safe_defaults(ctx: ToolContext) -> None:
    tools = tool_definitions(ctx)
    tool_names = [t["name"] for t in tools]
    assert "project_status" in tool_names
    assert "analyse_pdf" in tool_names
    assert "ask_warehouse" in tool_names
    assert "load_pdf_to_bigquery" not in tool_names


def test_tools_call_missing_argument_raises_key_error(ctx: ToolContext) -> None:
    with pytest.raises(KeyError, match="pdf_path"):
        call_tool(ctx, "analyse_pdf", {})
