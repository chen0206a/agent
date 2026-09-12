"""TEST-ONLY ASGI app: real auth/business/Agent, deterministic scripted model."""

import os
import re

from app.agent.evaluation import case_provider, tool_reply
from app.core.config import Settings
from app.db.seed import seed
from app.db.session import initialize, write_transaction
from app.main import create_app
from app.models.auth import Account
from app.services.auth import password_hash

settings = Settings(
    _env_file=None,
    database_url=os.environ["STAGE4_TEST_DATABASE"],
    frontend_origins="http://127.0.0.1:3810",
    llm_model="",
    llm_api_key="",
    log_level="WARNING",
)
app = create_app(settings)
initialize(app.state.engine)
seed(app.state.sessions)
with write_transaction(app.state.sessions) as session:
    hashed = password_hash("E2e-only-password-42")
    for user_id in range(1, 11):
        session.add(
            Account(username=f"customer{user_id}", user_id=user_id, role="customer", password_hash=hashed)
        )
    session.add(Account(username="admin", role="admin", password_hash=password_hash("E2e-admin-password-42")))


class BrowserFixtureProvider:
    name, model, is_live = "scripted-browser-fixture", "NOT-A-REAL-MODEL", False

    def __init__(self):
        self.plan = None

    def complete(self, messages, tools, timeout):
        if self.plan:
            return self.plan.complete(messages, tools, timeout)
        query = [m["content"] for m in messages if m["role"] == "user"][-1]
        if "别人" in query or "管理员" in query:
            return tool_reply("finish_response", {"kind": "REFUSE_UNAUTHORIZED"})
        match = re.search(r"用户选择的订单：(\d+)", messages[0]["content"]) or re.search(r"(10\d\d)", query)
        if not match:
            return tool_reply("finish_response", {"kind": "ASK_ORDER"})
        order = int(match[1])
        case = {"order_id": order, "message": query, "issue": "CANCEL", "action": "CANCEL_AND_REFUND"}
        if order == 1010:
            case.update(issue="NOT_RECEIVED", action="CREATE_LOGISTICS_TICKET", shipment=True)
        elif order == 1003:
            case.update(issue="NO_REASON_RETURN", action="RETURN_AND_REFUND", quantity=1)
        self.plan = case_provider(case)
        return self.plan.complete(messages, tools, timeout)


app.state.agent.provider_factory = BrowserFixtureProvider
