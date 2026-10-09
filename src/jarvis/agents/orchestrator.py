from uuid import uuid4

from sqlalchemy.orm import Session

from jarvis.agents.specialists import select_specialist
from jarvis.models import ActivityRun, Approval
from jarvis.schemas import CommandRequest, PermissionLevel, PlanResponse, RunStatus
from jarvis.security.permissions import classify_permission


class Orchestrator:
    def plan(self, request: CommandRequest, session: Session) -> PlanResponse:
        specialist = select_specialist(request.goal)
        permission = classify_permission(request.goal)
        run_id = uuid4()

        approval = None
        if permission == PermissionLevel.HIGH_IMPACT:
            approval = Approval(
                run_id=run_id,
                action_summary=request.goal,
                status="pending",
            )
            session.add(approval)
            session.flush()

        status = RunStatus.WAITING_FOR_APPROVAL if approval else RunStatus.PARTIAL_SUCCESS
        summary = (
            "High-impact action is waiting for explicit approval; no action was executed."
            if approval
            else "A plan was prepared. No external tools or specialist execution providers are configured."
        )
        run = ActivityRun(
            id=run_id,
            goal=request.goal,
            agent=specialist.name,
            permission_level=int(permission),
            status=status.value,
            summary=summary,
            approval_id=approval.id if approval else None,
        )
        session.add(run)
        session.commit()
        return PlanResponse(
            run_id=run_id,
            agent=specialist.name,
            permission_level=permission,
            status=status,
            summary=summary,
            plan=list(specialist.steps),
            approval_id=approval.id if approval else None,
        )
