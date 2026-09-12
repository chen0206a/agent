from app.repositories.portal import PortalRepository
from app.schemas.api import ActionRead
from app.schemas.portal import DashboardRead, RunRead


def public_trace(value):
    if isinstance(value, dict):
        return {
            k: public_trace(v) for k, v in value.items() if k not in {"reasoning_content", "system_prompt"}
        }
    if isinstance(value, list):
        return [public_trace(v) for v in value if not (isinstance(v, dict) and v.get("role") == "system")]
    return value


class PortalService:
    def __init__(self, sessions):
        self.sessions = sessions

    def actions(self, user_id, risk, limit, offset, status=None):
        with self.sessions() as session:
            return [
                ActionRead.model_validate(a)
                for a in PortalRepository(session).actions(user_id, risk, limit, offset, status)
            ]

    def runs(self, user_id, order_id, limit, offset):
        with self.sessions() as session:
            return [
                RunRead(
                    id=r.id,
                    user_id=r.user_id,
                    order_id=r.order_id,
                    ticket_id=r.ticket_id,
                    user_query=r.user_query,
                    reply=d.reply,
                    outcome=d.outcome,
                    status=r.status,
                    llm_calls=r.llm_calls,
                    latency_ms=r.latency_ms,
                    created_at=r.created_at,
                    parent_run_id=d.parent_run_id,
                )
                for r, d in PortalRepository(session).runs(user_id, order_id, limit, offset)
            ]

    def dashboard(self):
        with self.sessions() as session:
            return DashboardRead(**PortalRepository(session).dashboard())
