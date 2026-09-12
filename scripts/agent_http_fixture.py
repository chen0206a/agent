"""Explicit test-only ASGI entrypoint. Never used by scripts/start.ps1."""

from app.agent.evaluation import case_provider
from app.main import create_app

app = create_app()
app.state.agent.provider_factory = lambda: case_provider(
    {
        "order_id": 1001,
        "message": "取消订单1001",
        "issue": "CANCEL",
        "action": "CANCEL_AND_REFUND",
    }
)
