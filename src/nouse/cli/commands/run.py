"""
nouse run — interactive REPL with full graph R/W integration.

  nouse run                    # interactive, uses model from policy
  nouse run "What is NoUse?"   # single query
  nouse run --model gemma4:26b # explicit model upgrade
"""
from __future__ import annotations

import asyncio
import sys
from typing import Optional

import typer

app = typer.Typer(help="Run NoUse as an interactive epistemic assistant.")


def _get_brain():
    from nouse.inject import NouseBrain
    return NouseBrain()


async def _query_once(question: str, model: str | None, brain) -> str:
    from nouse.llm.agent import NouseAgent

    agent = NouseAgent(model)

    # 1. Query graph for context
    try:
        nodes = brain.query(question)
        context_lines = []
        for n in (nodes or [])[:8]:
            src = n.get("src") or n.get("node") or ""
            rel = n.get("rel_type") or "→"
            tgt = n.get("tgt") or ""
            conf = n.get("confidence") or n.get("weight") or ""
            conf_str = f" [{conf:.2f}]" if isinstance(conf, float) else ""
            if src and tgt:
                context_lines.append(f"  {src} {rel} {tgt}{conf_str}")
            elif src:
                context_lines.append(f"  {src}{conf_str}")
        context = "\n".join(context_lines)
    except Exception:
        context = ""

    # 2. Generate answer grounded in context
    answer = await agent.chat(question, context=context)

    # 3. Learn from the interaction
    try:
        brain.learn(question, answer, source="nouse_run")
    except Exception:
        pass

    return answer


def _run_repl(model: str | None) -> None:
    brain = _get_brain()
    model_label = model or "default"

    typer.echo(f"NoUse REPL — model: {model_label}")
    typer.echo("Type your question. Ctrl-C or 'exit' to quit.\n")

    while True:
        try:
            question = input("you> ").strip()
        except (KeyboardInterrupt, EOFError):
            typer.echo("\nBye.")
            break

        if not question or question.lower() in {"exit", "quit", "q"}:
            typer.echo("Bye.")
            break

        try:
            answer = asyncio.run(_query_once(question, model, brain))
            typer.echo(f"\nnouse> {answer}\n")
        except KeyboardInterrupt:
            typer.echo("\n[interrupted]")
        except Exception as e:
            typer.echo(f"\n[error] {e}\n", err=True)


@app.command(name="run")
def run_cmd(
    question: Optional[str] = typer.Argument(None, help="Question to ask (non-interactive)"),
    model: str = typer.Option("", "--model", "-m", help="Model to use (default: from policy)"),
) -> None:
    """Run NoUse as an epistemic assistant with persistent graph memory."""
    _model = model.strip() or None

    if question:
        brain = _get_brain()
        try:
            answer = asyncio.run(_query_once(question, _model, brain))
            typer.echo(answer)
        except Exception as e:
            typer.echo(f"Error: {e}", err=True)
            raise typer.Exit(1)
    else:
        _run_repl(_model)
