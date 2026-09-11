"""Installed now, used later (P3+ streaming endpoint) per the kickoff spec.
P1 ships only a health check -- no UI, no streaming, per P1 scope."""
from fastapi import FastAPI

app = FastAPI(title="Consilium", version="0.1.0")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
