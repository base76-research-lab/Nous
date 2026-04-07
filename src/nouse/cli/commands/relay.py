"""
nouse relay — cross-model session handoff CLI.

  nouse relay open "Implement domain bootstrap"
  nouse relay list
  nouse relay show <session_id>
  nouse relay continue <session_id>
  nouse relay update <session_id> --decision "use brain.add()" --why "learn() broken"
  nouse relay close <session_id>
"""
from __future__ import annotations

import typer
from typing import Optional

app = typer.Typer(help="Cross-model session relay — hand off work between any models.")


@app.command(name="open")
def relay_open_cmd(
    goal: str = typer.Argument(..., help="What this session is trying to accomplish"),
    model: str = typer.Option("", "--model", "-m", help="Model starting the session"),
    session_id: Optional[str] = typer.Option(None, "--id", help="Custom session ID"),
) -> None:
    """Start a new relay session."""
    from nouse.session.relay import relay_open
    import os

    _model = model or os.getenv("NOUSE_RELAY_MODEL", "unknown")
    relay = relay_open(goal, model=_model, session_id=session_id or None)
    typer.echo(f"Relay opened: {relay['session_id']}")
    typer.echo(f"Goal: {relay['goal']}")
    typer.echo(f"\nTo continue from another model:")
    typer.echo(f"  nouse relay continue {relay['session_id']}")


@app.command(name="list")
def relay_list_cmd(
    status: Optional[str] = typer.Option(None, "--status", "-s", help="Filter by status"),
    limit: int = typer.Option(10, "--limit", "-n"),
) -> None:
    """List relay sessions."""
    from nouse.session.relay import relay_list

    sessions = relay_list(status=status, limit=limit)
    if not sessions:
        typer.echo("No relay sessions found.")
        return

    for r in sessions:
        age = r.get("updated_at", "")[:19].replace("T", " ")
        status_str = r.get("status", "?")
        handoffs = r.get("handoffs", 0)
        goal = r.get("goal", "")[:50]
        model = r.get("last_active_model", "?")
        typer.echo(
            f"  {r['session_id']:<22} [{status_str:<11}] {age}  "
            f"handoffs={handoffs}  model={model}\n"
            f"  {'':22} {goal}"
        )


@app.command(name="show")
def relay_show_cmd(
    session_id: str = typer.Argument(..., help="Session ID to show"),
) -> None:
    """Show full relay session details."""
    from nouse.session.relay import relay_get
    import json

    relay = relay_get(session_id)
    if not relay:
        typer.echo(f"Session '{session_id}' not found.", err=True)
        raise typer.Exit(1)

    typer.echo(json.dumps(relay, indent=2, ensure_ascii=False))


@app.command(name="continue")
def relay_continue_cmd(
    session_id: str = typer.Argument(..., help="Session ID to continue"),
    model: str = typer.Option("", "--model", "-m", help="Model picking up the session"),
) -> None:
    """Print context block for the next model to pick up this session."""
    from nouse.session.relay import relay_continue
    import os

    _model = model or os.getenv("NOUSE_RELAY_MODEL", "unknown")
    block = relay_continue(session_id, model=_model)
    typer.echo(block)


@app.command(name="update")
def relay_update_cmd(
    session_id: str = typer.Argument(..., help="Session ID to update"),
    decision: Optional[str] = typer.Option(None, "--decision", "-d", help="Decision made"),
    why: str = typer.Option("", "--why", "-w", help="Why this decision"),
    confidence: float = typer.Option(0.8, "--confidence", "-c"),
    question: Optional[str] = typer.Option(None, "--question", "-q", help="Open question"),
    file: Optional[str] = typer.Option(None, "--file", "-f", help="File touched"),
    node: Optional[str] = typer.Option(None, "--node", "-n", help="NoUse node used"),
    summary: Optional[str] = typer.Option(None, "--summary", "-s", help="Current state summary"),
    model: str = typer.Option("", "--model", "-m"),
) -> None:
    """Update a relay session with new work context."""
    from nouse.session.relay import relay_update
    import os

    _model = model or os.getenv("NOUSE_RELAY_MODEL", "unknown")
    result = relay_update(
        session_id,
        decision=decision,
        decision_why=why,
        decision_confidence=confidence,
        open_question=question,
        file_touched=file,
        node_used=node,
        summary=summary,
        model=_model,
    )
    if not result:
        typer.echo(f"Session '{session_id}' not found.", err=True)
        raise typer.Exit(1)
    typer.echo(f"Updated: {session_id}")
    if decision:
        typer.echo(f"  Decision: {decision}")
    if summary:
        typer.echo(f"  Summary: {summary}")


@app.command(name="close")
def relay_close_cmd(
    session_id: str = typer.Argument(..., help="Session ID to close"),
) -> None:
    """Mark a relay session as closed."""
    from nouse.session.relay import relay_close

    result = relay_close(session_id)
    if not result:
        typer.echo(f"Session '{session_id}' not found.", err=True)
        raise typer.Exit(1)
    typer.echo(f"Closed: {session_id}")
