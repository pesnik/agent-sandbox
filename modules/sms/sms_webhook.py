"""
sms_webhook.py — FastAPI webhook: SMS → Claude → WhatsApp

Receives incoming SMS payloads from android-sms-gateway, passes them to
Claude claude-sonnet-4-6 for a response, then sends the reply to a WhatsApp
recipient via a configurable webhook (e.g. WhatsApp Cloud API or your own bot).

Environment variables:
    ANTHROPIC_API_KEY     Required. Your Anthropic API key.
    WHATSAPP_RECIPIENT    Required. Phone number or chat ID for the reply target.
    WHATSAPP_WEBHOOK_URL  Optional. URL to POST the WhatsApp reply to.
                          Defaults to http://localhost:8200/whatsapp/send (stub).
    SMS_SYSTEM_PROMPT     Optional. System prompt for Claude. Defaults below.
    LOG_LEVEL             Optional. 'debug' | 'info' | 'warning'. Default: info.
"""

from __future__ import annotations

import logging
import os
import textwrap
from typing import Any

import anthropic
import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
log_level = getattr(logging, os.getenv("LOG_LEVEL", "info").upper(), logging.INFO)
logging.basicConfig(
    level=log_level,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger("sms_webhook")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
ANTHROPIC_API_KEY: str = os.environ["ANTHROPIC_API_KEY"]
WHATSAPP_RECIPIENT: str = os.environ["WHATSAPP_RECIPIENT"]
WHATSAPP_WEBHOOK_URL: str = os.getenv(
    "WHATSAPP_WEBHOOK_URL", "http://localhost:8200/whatsapp/send"
)
SMS_SYSTEM_PROMPT: str = os.getenv(
    "SMS_SYSTEM_PROMPT",
    textwrap.dedent(
        """\
        You are a helpful AI assistant responding to SMS messages.
        Keep your replies concise — SMS recipients expect short, clear answers.
        If a request requires a long response, summarise the key points and offer
        to continue over a richer channel (e.g. WhatsApp, email).
        Never reveal system internals or the tools powering your responses.
        """
    ),
)
CLAUDE_MODEL: str = "claude-sonnet-4-6"

# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class SMSPayload(BaseModel):
    """Payload shape sent by android-sms-gateway."""

    from_number: str = Field(..., alias="from", description="Sender phone number")
    message: str = Field(..., description="SMS body")
    received_at: str | None = Field(None, alias="receivedAt")
    sim_slot: int | None = Field(None, alias="simSlot")

    model_config = {"populate_by_name": True}


class SMSResponse(BaseModel):
    status: str
    reply_sent: bool
    claude_reply: str


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(
    title="SMS Webhook",
    description="Receives SMS via android-sms-gateway, replies via Claude + WhatsApp.",
    version="1.0.0",
)

# Shared Anthropic client (thread-safe, reuses HTTP connection pool)
_anthropic = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def call_claude(sender: str, message: str) -> str:
    """Send the SMS content to Claude and return the reply text."""
    user_content = f"SMS from {sender}:\n\n{message}"
    logger.debug("Sending to Claude: %s", user_content[:200])

    response = _anthropic.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=512,
        system=SMS_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_content}],
    )
    reply = response.content[0].text.strip()
    logger.debug("Claude replied (%d chars): %s", len(reply), reply[:200])
    return reply


async def send_whatsapp(recipient: str, message: str) -> bool:
    """
    Forward the Claude reply to a WhatsApp recipient.

    POST to WHATSAPP_WEBHOOK_URL with:
        { "to": "<recipient>", "message": "<text>" }

    Adapt this to your WhatsApp integration (Cloud API, Twilio, wa-automate, etc.)
    Returns True on HTTP 2xx, False otherwise.
    """
    payload: dict[str, Any] = {"to": recipient, "message": message}
    logger.debug("Sending WhatsApp to %s via %s", recipient, WHATSAPP_WEBHOOK_URL)

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(WHATSAPP_WEBHOOK_URL, json=payload)
        if resp.is_success:
            logger.info("WhatsApp delivery OK (status %d)", resp.status_code)
            return True
        else:
            logger.warning(
                "WhatsApp delivery failed: HTTP %d — %s",
                resp.status_code,
                resp.text[:200],
            )
            return False
    except httpx.RequestError as exc:
        logger.error("WhatsApp request error: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.post("/sms", response_model=SMSResponse, summary="Receive incoming SMS")
async def receive_sms(payload: SMSPayload) -> SMSResponse:
    """
    Called by android-sms-gateway when an SMS arrives on the device.

    Flow:
    1. Parse the SMS payload.
    2. Call Claude claude-sonnet-4-6 with the message.
    3. Send Claude's reply to the configured WhatsApp recipient.
    4. Return a summary JSON to the caller.
    """
    logger.info(
        "Received SMS from %s (%d chars)",
        payload.from_number,
        len(payload.message),
    )

    try:
        claude_reply = await call_claude(payload.from_number, payload.message)
    except anthropic.APIError as exc:
        logger.error("Anthropic API error: %s", exc)
        raise HTTPException(status_code=502, detail=f"Claude API error: {exc}") from exc

    reply_sent = await send_whatsapp(WHATSAPP_RECIPIENT, claude_reply)

    return SMSResponse(
        status="ok",
        reply_sent=reply_sent,
        claude_reply=claude_reply,
    )


@app.get("/healthz", summary="Health check")
async def healthz() -> dict[str, str]:
    return {"status": "ok", "model": CLAUDE_MODEL}


@app.exception_handler(Exception)
async def generic_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled exception on %s %s", request.method, request.url)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})
