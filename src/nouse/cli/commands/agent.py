from __future__ import annotations

import asyncio
import json

import typer

from nouse.cli.console import console

app = typer.Typer(help="Folder-driven agent pipeline (ICM/Larynx). See ICM-agents.md.")


@app.command(name="run")
def agent_run(
    text: str = typer.Argument(..., help="The request text (e.g. from Voxtype push-to-talk)."),
    json_out: bool = typer.Option(False, "--json", help="Print the raw result dict as JSON."),
) -> None:
    """Run one request through the stage 01-05 pipeline and print the answer."""
    from nouse.agent_system.pipeline import run_pipeline

    result = asyncio.run(run_pipeline(text))
    if json_out:
        console.print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    console.print(result.get("content", ""))
    if not result.get("ok"):
        console.print(f"[dim]({result.get('error_code')}, run {result.get('run_id')})[/dim]")
