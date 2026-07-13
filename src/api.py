"""
FastAPI application exposing support ticket triage as a REST endpoint.
"""

import asyncio
import logging
from typing import Any, Optional, Union

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from src.triage import triage_ticket

# ---------------------------------------------------------------------------
# App & Logging
# ---------------------------------------------------------------------------

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Support Ticket Triage API",
    description="AI-powered support ticket triage and classification.",
    version="0.1.0",
)

# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class TicketInput(BaseModel):
    """Accepts either raw_text OR subject+body (matching tickets.json schema)."""

    raw_text: Optional[str] = Field(
        None,
        description="Free-text ticket content. Use this OR subject+body, not both.",
    )
    subject: Optional[str] = Field(None, description="Ticket subject line.")
    body: Optional[str] = Field(None, description="Ticket body text.")
    product: Optional[str] = Field(None, description="Product name if known.")
    product_area: Optional[str] = Field(None, description="Product area if known.")
    plan_tier: Optional[str] = Field(None, description="Customer plan tier.")
    channel: Optional[str] = Field(None, description="Submission channel.")
    tags: Optional[list[str]] = Field(None, description="Tags on the ticket.")


class TriageOutput(BaseModel):
    """Structured triage result."""

    product_area: str
    issue_category: str
    urgency_tier: str
    reasoning: str
    matched_kb_doc: Optional[str] = None
    recommended_team: str
    draft_response: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/triage", response_model=TriageOutput)
async def triage_endpoint(ticket: TicketInput) -> TriageOutput:
    """
    Triage a support ticket.

    Send either ``raw_text`` for free-form input, or ``subject`` + ``body``
    (plus optional metadata) to match the tickets.json schema.
    """
    # Build input for triage_ticket
    if ticket.raw_text:
        triage_input: Union[str, dict[str, Any]] = ticket.raw_text
    elif ticket.subject or ticket.body:
        triage_input = {
            k: v
            for k, v in ticket.model_dump().items()
            if v is not None and k != "raw_text"
        }
    else:
        raise HTTPException(
            status_code=422,
            detail="Provide either 'raw_text' or at least one of 'subject'/'body'.",
        )

    try:
        result = await asyncio.to_thread(triage_ticket, triage_input)
    except Exception as exc:
        logger.error("Error during triage_ticket execution", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal Server Error") from exc

    if not isinstance(result, dict):
        raise HTTPException(status_code=500, detail="Unexpected stream returned")

    return TriageOutput(**result)
