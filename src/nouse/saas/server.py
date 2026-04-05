"""
nouse.saas.server — Nouse Cloud API (multi-tenant).

Starta:
    nouse-saas --port 8766

Alla endpoints kräver:
    Authorization: Bearer nsk-<key>
"""
from __future__ import annotations

import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel

from nouse.saas.auth import validate_key
from nouse.saas.tenant import db_path_for

app = FastAPI(
    title="Nouse Cloud API",
    version="1.0.0",
    description="Multi-tenant cognitive substrate API. Each API key maps to an isolated brain.",
)


# ── Auth dependency ────────────────────────────────────────────────────────────

def require_tenant(authorization: str = Header(...)) -> str:
    raw = authorization.removeprefix("Bearer ").strip()
    tenant_id = validate_key(raw)
    if not tenant_id:
        raise HTTPException(status_code=401, detail="Ogiltig eller inaktiv API-nyckel.")
    return tenant_id


def _brain(tenant_id: str):
    from nouse.inject import NouseBrain
    return NouseBrain(db_path=db_path_for(tenant_id))


# ── Request/Response models ────────────────────────────────────────────────────

class QueryRequest(BaseModel):
    question: str
    top_k: int = 6

class LearnRequest(BaseModel):
    prompt: str
    response: str = ""
    source: str = "conversation"

class ContextRequest(BaseModel):
    query: str
    top_k: int = 6
    max_axioms: int = 15

class AddRequest(BaseModel):
    src: str
    rel_type: str
    tgt: str
    why: str = ""
    evidence_score: float = 0.6


# ── Endpoints ──────────────────────────────────────────────────────────────────

@app.get("/v1/health")
def health():
    return {"status": "ok"}


@app.post("/v1/brain/query")
def brain_query(req: QueryRequest, tenant_id: str = Depends(require_tenant)):
    brain = _brain(tenant_id)
    result = brain.query(req.question, top_k=req.top_k)
    return {
        "query":      result.query,
        "confidence": result.confidence,
        "domains":    result.domains,
        "concepts":   result.concepts,
        "axioms":     [
            {"src": a.src, "rel": a.rel, "tgt": a.tgt,
             "evidence": a.evidence, "why": a.why}
            for a in result.axioms
        ],
        "context_block": result.context_block(),
    }


@app.post("/v1/brain/context")
def brain_context(req: ContextRequest, tenant_id: str = Depends(require_tenant)):
    brain = _brain(tenant_id)
    return {"context": brain.context_block(req.query, top_k=req.top_k, max_axioms=req.max_axioms)}


@app.post("/v1/brain/learn")
def brain_learn(req: LearnRequest, tenant_id: str = Depends(require_tenant)):
    brain = _brain(tenant_id)
    brain.learn(req.prompt, req.response, source=req.source)
    return {"status": "ok"}


@app.post("/v1/brain/add")
def brain_add(req: AddRequest, tenant_id: str = Depends(require_tenant)):
    brain = _brain(tenant_id)
    brain.add(req.src, req.rel_type, req.tgt, why=req.why, evidence_score=req.evidence_score)
    return {"status": "ok"}


@app.get("/v1/brain/stats")
def brain_stats(tenant_id: str = Depends(require_tenant)):
    brain = _brain(tenant_id)
    return brain.stats()


# ── Entry point ────────────────────────────────────────────────────────────────

def main():
    import typer
    cli = typer.Typer()

    @cli.command()
    def run(port: int = typer.Option(8766, "--port", "-p")):
        """Starta Nouse Cloud API-server."""
        typer.echo(f"Nouse SaaS API → http://0.0.0.0:{port}/v1/health")
        uvicorn.run("nouse.saas.server:app", host="0.0.0.0", port=port, reload=False)

    cli()


if __name__ == "__main__":
    main()
