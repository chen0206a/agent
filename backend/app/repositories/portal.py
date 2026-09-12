from sqlalchemy import func, select

from app.models.entities import ActionRequest, AgentRun, AgentRunDetail, Approval, ModelCall, ToolCall


class PortalRepository:
    def __init__(self, session):
        self.session = session

    def actions(self, user_id, risk, limit, offset, status=None):
        query = select(ActionRequest)
        if user_id is not None:
            query = query.where(ActionRequest.user_id == user_id)
        if risk:
            query = query.where(ActionRequest.risk_level == risk)
        if status:
            query = query.where(ActionRequest.execution_status == status)
        return list(self.session.scalars(query.order_by(ActionRequest.id.desc()).limit(limit).offset(offset)))

    def runs(self, user_id, order_id, limit, offset):
        query = select(AgentRun, AgentRunDetail).join(AgentRunDetail, AgentRunDetail.run_id == AgentRun.id)
        if user_id is not None:
            query = query.where(AgentRun.user_id == user_id)
        if order_id is not None:
            query = query.where(AgentRun.order_id == order_id)
        return self.session.execute(query.order_by(AgentRun.id.desc()).limit(limit).offset(offset)).all()

    def dashboard(self):
        def count(model, *conditions):
            return self.session.scalar(select(func.count()).select_from(model).where(*conditions))

        def total(column, *conditions):
            return self.session.scalar(select(func.coalesce(func.sum(column), 0)).where(*conditions))

        completed = count(AgentRun, AgentRun.status != "RUNNING")
        reviewed = self.session.scalar(
            select(func.count())
            .select_from(AgentRunDetail)
            .join(Approval, Approval.action_request_id == AgentRunDetail.action_request_id)
        )
        automatic = count(
            AgentRunDetail, AgentRunDetail.outcome.in_(["READY", "WAITING_RETURN", "LOGISTICS_PENDING"])
        )
        runs = count(AgentRun)
        return dict(
            total_runs=runs,
            successful_runs=count(AgentRun, AgentRun.status == "SUCCESS"),
            completed_runs=completed,
            human_review_count=reviewed,
            rejected_or_clarified_count=count(
                AgentRunDetail, AgentRunDetail.outcome.in_(["REFUSED", "POLICY_DENIED", "NEED_MORE_INFO"])
            ),
            automation_rate=automatic / completed if completed else 0,
            human_review_rate=reviewed / completed if completed else 0,
            avg_llm_calls=total(AgentRun.llm_calls) / runs if runs else 0,
            avg_tool_calls=count(ToolCall) / runs if runs else 0,
            input_tokens=total(ModelCall.input_tokens, ModelCall.is_live.is_(True)),
            output_tokens=total(ModelCall.output_tokens, ModelCall.is_live.is_(True)),
            unknown_usage_calls=count(
                ModelCall,
                ModelCall.is_live.is_(True),
                (ModelCall.input_tokens.is_(None) | ModelCall.output_tokens.is_(None)),
            ),
            avg_latency_ms=total(AgentRun.latency_ms, AgentRun.status != "RUNNING") / completed
            if completed
            else 0,
            agent_error_count=count(AgentRun, AgentRun.status == "FAILED"),
            pending_approvals=count(Approval, Approval.status == "PENDING"),
        )
