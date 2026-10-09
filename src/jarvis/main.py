import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from uuid import UUID, uuid4

import re

from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.responses import FileResponse
from redis import Redis
from sqlalchemy import select, update

from jarvis.agents.copilot import CopilotCLIChatRouter
from jarvis.agents.ollama import OllamaIntentRouter
from jarvis.agents.orchestrator import Orchestrator
from jarvis.agents.model_errors import ModelInvalidResponse, ModelNotConfigured, ModelUnavailable
from jarvis.agents.openai import OpenAIChatRouter
from jarvis.config import (
    get_api_token,
    get_copilot_model,
    get_database_url,
    get_model_provider,
    get_ollama_model,
    get_ollama_url,
    get_openai_api_key,
    get_openai_base_url,
    get_openai_model,
    get_redis_url,
    get_workspace,
)
from jarvis.db import Base, make_session_factory
from jarvis.local_tools import LocalSystemTools
from jarvis.job_search import (
    JobResponse,
    JobSearchRequest,
    JobSearchResponse,
    get_saved_jobs,
    search_jobs,
)
from jarvis.models import (
    ActivityRun,
    Approval,
    CareerProfileRecord,
    LocalAction,
    MasterResumeVersion,
    MemoryItem,
)
from jarvis.schemas import (
    AssistantChatResponse,
    AssistantChatRequest,
    AssistantStatusResponse,
    ActivityResponse,
    ApprovalDecision,
    ApprovalResponse,
    CareerProfile,
    CommandRequest,
    LocalActionRequest,
    LocalActionResponse,
    MasterResumeCreate,
    MasterResumeVersionResponse,
    MasterResumeVersionSummary,
    MemoryCreate,
    MemoryResponse,
    PlanResponse,
    TaskCreate,
    TaskResponse,
    TaskUpdate,
)
from jarvis.security.auth import require_api_token
from jarvis.tasks.repository import RedisTaskRepository, TaskStoreUnavailable


def create_app(
    database_url: str | None = None,
    redis_url: str | None = None,
    api_token: str | None = None,
    create_tables: bool = True,
    workspace: str | Path | None = None,
    model_router=None,
) -> FastAPI:
    database_url = database_url or get_database_url()
    redis_url = redis_url or get_redis_url()
    session_factory = make_session_factory(database_url)
    redis_client = Redis.from_url(redis_url, decode_responses=True)
    local_tools = LocalSystemTools(workspace or get_workspace())
    model_provider = get_model_provider()
    if model_router is None:
        if model_provider == "openai":
            model_router = OpenAIChatRouter(
                api_key=get_openai_api_key(),
                model=get_openai_model(),
                base_url=get_openai_base_url(),
            )
        elif model_provider == "ollama":
            model_router = OllamaIntentRouter(get_ollama_url(), get_ollama_model())
        elif model_provider == "copilot":
            model_router = CopilotCLIChatRouter(
                model=get_copilot_model(),
                working_directory=workspace or get_workspace(),
            )
        else:
            raise ValueError("JARVIS_MODEL_PROVIDER must be 'copilot', 'openai', or 'ollama'")

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        if create_tables:
            Base.metadata.create_all(session_factory.kw["bind"])
        yield
        redis_client.close()
        session_factory.kw["bind"].dispose()

    application = FastAPI(
        title="Taj Personal Assistant API",
        version="0.1.0",
        description="Taj, Suren's personal assistant API.",
        lifespan=lifespan,
    )
    application.state.api_token = api_token if api_token is not None else get_api_token()
    application.state.session_factory = session_factory
    application.state.task_repository = RedisTaskRepository(redis_client)
    application.state.orchestrator = Orchestrator()
    application.state.local_tools = local_tools
    application.state.model_router = model_router
    application.state.model_provider = model_provider

    @application.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @application.get("/", include_in_schema=False)
    def assistant_ui() -> FileResponse:
        return FileResponse(Path(__file__).parent / "static" / "index.html")

    @application.get(
        "/v1/assistant/status",
        response_model=AssistantStatusResponse,
        dependencies=[Depends(require_api_token)],
    )
    def assistant_status() -> AssistantStatusResponse:
        model_status = application.state.model_router.status()
        return AssistantStatusResponse(
            local_tools="ready",
            model_provider=application.state.model_provider,
            model_configured=model_status.configured,
            model_reachable=model_status.reachable,
            model_name=model_status.model,
            model_available=model_status.model_available,
        )

    @application.post("/v1/commands", response_model=PlanResponse, dependencies=[Depends(require_api_token)])
    def submit_command(request: CommandRequest) -> PlanResponse:
        with session_factory() as session:
            return application.state.orchestrator.plan(request, session)

    @application.get(
        "/v1/activity",
        response_model=list[ActivityResponse],
        dependencies=[Depends(require_api_token)],
    )
    def list_activity(limit: int = Query(default=50, ge=1, le=200)) -> list[ActivityRun]:
        with session_factory() as session:
            return list(session.scalars(select(ActivityRun).order_by(ActivityRun.created_at.desc()).limit(limit)))

    @application.get(
        "/v1/approvals",
        response_model=list[ApprovalResponse],
        dependencies=[Depends(require_api_token)],
    )
    def list_approvals(pending_only: bool = False) -> list[Approval]:
        with session_factory() as session:
            query = select(Approval).order_by(Approval.created_at.desc())
            if pending_only:
                query = query.where(Approval.status == "pending")
            return list(session.scalars(query))

    @application.post(
        "/v1/approvals/{approval_id}/decision",
        response_model=ApprovalResponse,
        dependencies=[Depends(require_api_token)],
    )
    def decide_approval(approval_id: UUID, decision: ApprovalDecision) -> Approval:
        with session_factory() as session:
            approval = session.get(Approval, approval_id)
            if approval is None:
                raise HTTPException(status_code=404, detail="Approval not found")
            if approval.status != "pending":
                raise HTTPException(status_code=409, detail="Approval has already been decided")
            approval.status = "approved" if decision.approved else "rejected"
            approval.decision_note = decision.note
            approval.decided_at = datetime.now(timezone.utc)
            run = session.get(ActivityRun, approval.run_id)
            if run is not None:
                action = session.scalar(select(LocalAction).where(LocalAction.run_id == run.id))
                if action is not None:
                    action.status = "approved" if decision.approved else "rejected"
                    action.summary = (
                        "Approval granted; waiting for explicit execution."
                        if decision.approved
                        else "Approval rejected; action was not executed."
                    )
                run.status = "PARTIAL_SUCCESS" if decision.approved else "FAILED"
                run.summary = (
                    "Approval granted; the action has not yet been executed."
                    if decision.approved
                    else "Approval rejected; the requested action was not executed."
                )
            session.commit()
            session.refresh(approval)
            return approval

    @application.post(
        "/v1/assistant/actions",
        response_model=LocalActionResponse,
        dependencies=[Depends(require_api_token)],
    )
    def perform_local_action(request: LocalActionRequest) -> LocalActionResponse:
        return _prepare_local_action(application, request)

    @application.post(
        "/v1/jobs/search",
        response_model=JobSearchResponse,
        dependencies=[Depends(require_api_token)],
    )
    def find_jobs(request: JobSearchRequest) -> JobSearchResponse:
        with session_factory() as session:
            return _run_job_search(session, request)

    @application.get(
        "/v1/jobs",
        response_model=list[JobResponse],
        dependencies=[Depends(require_api_token)],
    )
    def list_saved_jobs(
        minimum_match_score: int = Query(default=0, ge=0, le=100),
        limit: int = Query(default=50, ge=1, le=100),
        role: str = Query(default="", max_length=240),
        location: str = Query(default="", max_length=240),
    ) -> list[JobResponse]:
        with session_factory() as session:
            return get_saved_jobs(session, minimum_match_score, limit, role, location)

    @application.post(
        "/v1/assistant/chat",
        response_model=AssistantChatResponse,
        dependencies=[Depends(require_api_token)],
    )
    def assistant_chat(request: AssistantChatRequest) -> AssistantChatResponse:
        search_request = _parse_job_search_request(request.goal)
        if search_request is not None:
            with session_factory() as session:
                result = _run_job_search(session, search_request)
            if result.status == "WAITING_FOR_USER":
                response_text = result.sources[0].error or "Add a target role or keyword to search for jobs."
            elif result.status == "NEEDS_CONFIGURATION":
                response_text = (
                    "Job search is not configured. Configure JOB_SEARCH_SOURCES "
                    "with at least one supported provider (arbeitnow or remoteok)."
                )
            elif result.status == "FAILED":
                failed = "; ".join(
                    f"{source.source}: {source.error}" for source in result.sources if source.error
                )
                response_text = f"Job search failed for all configured sources. {failed}"
            elif result.jobs:
                response_text = (
                    f"Found {result.total_found} matching job(s) from live public sources; "
                    f"removed {result.duplicates_removed} duplicate listing(s). "
                    "Results are ranked using your saved profile and master resume."
                )
            else:
                response_text = "Search completed, but no listings met the requested filters and match threshold."
            app_requested = bool(re.search(r"\b(?:apply|applications?|submit)\b", request.goal, re.IGNORECASE))
            if app_requested:
                response_text += (
                    " Application preparation, browser form filling, and submission are not implemented yet; "
                    "no application was prepared or submitted."
                )
            return AssistantChatResponse(
                status="PARTIAL_SUCCESS" if app_requested and result.status == "SUCCESS" else result.status,
                response=response_text,
                job_search=result.model_dump(mode="json"),
            )
        try:
            intent = application.state.model_router.classify(request.goal, request.history)
        except ModelNotConfigured as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        except ModelUnavailable as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        except ModelInvalidResponse as error:
            raise HTTPException(status_code=502, detail=str(error)) from error
        if intent.decision == "answer":
            return AssistantChatResponse(status="PARTIAL_SUCCESS", response=intent.response or "")
        if intent.action is None:
            raise HTTPException(status_code=502, detail="Ollama selected an action without an action payload")
        action = _prepare_local_action(application, intent.action)
        status_by_action = {
            "pending_approval": "WAITING_FOR_APPROVAL",
            "success": "SUCCESS",
            "failed": "FAILED",
        }
        return AssistantChatResponse(
            status=status_by_action.get(action.status, "PARTIAL_SUCCESS"),
            response=action.summary,
            action=action,
        )

    @application.post(
        "/v1/assistant/actions/{action_id}/execute",
        response_model=LocalActionResponse,
        dependencies=[Depends(require_api_token)],
    )
    def execute_approved_action(action_id: UUID) -> LocalActionResponse:
        with session_factory() as session:
            action = session.get(LocalAction, action_id)
            if action is None:
                raise HTTPException(status_code=404, detail="Local action not found")
            if action.status != "approved" or action.approval_id is None:
                raise HTTPException(status_code=409, detail="Action must have an explicit approval before execution")
            approval = session.get(Approval, action.approval_id)
            if approval is None or approval.status != "approved":
                raise HTTPException(status_code=409, detail="Approval is not in an approved state")
            claimed = session.execute(
                update(LocalAction)
                .where(LocalAction.id == action_id, LocalAction.status == "approved")
                .values(status="running", summary="Approved action is running.")
            )
            if claimed.rowcount != 1:
                raise HTTPException(status_code=409, detail="Action is already running or has already completed")
            session.commit()
        return _execute_local_action(application, action_id)

    @application.get(
        "/v1/memory",
        response_model=list[MemoryResponse],
        dependencies=[Depends(require_api_token)],
    )
    def list_memory(category: str | None = None) -> list[MemoryItem]:
        with session_factory() as session:
            query = select(MemoryItem).where(MemoryItem.approved.is_(True)).order_by(MemoryItem.created_at.desc())
            if category:
                query = query.where(MemoryItem.category == category)
            return list(session.scalars(query))

    @application.post(
        "/v1/memory",
        response_model=MemoryResponse,
        status_code=status.HTTP_201_CREATED,
        dependencies=[Depends(require_api_token)],
    )
    def create_memory(memory: MemoryCreate) -> MemoryItem:
        with session_factory() as session:
            record = MemoryItem(category=memory.category, content=memory.content, approved=False)
            session.add(record)
            session.commit()
            session.refresh(record)
            return record

    @application.post(
        "/v1/memory/{memory_id}/approve",
        response_model=MemoryResponse,
        dependencies=[Depends(require_api_token)],
    )
    def approve_memory(memory_id: UUID) -> MemoryItem:
        with session_factory() as session:
            record = session.get(MemoryItem, memory_id)
            if record is None:
                raise HTTPException(status_code=404, detail="Memory item not found")
            if not record.approved:
                record.approved = True
                record.approved_at = datetime.now(timezone.utc)
                session.commit()
                session.refresh(record)
            return record

    @application.get(
        "/v1/profile",
        response_model=CareerProfile,
        dependencies=[Depends(require_api_token)],
    )
    def get_career_profile() -> CareerProfile:
        with session_factory() as session:
            record = session.get(CareerProfileRecord, 1)
            return CareerProfile.model_validate(record.data if record else {})

    @application.put(
        "/v1/profile",
        response_model=CareerProfile,
        dependencies=[Depends(require_api_token)],
    )
    def save_career_profile(profile: CareerProfile) -> CareerProfile:
        with session_factory() as session:
            record = session.get(CareerProfileRecord, 1)
            if record is None:
                record = CareerProfileRecord(id=1, data=profile.model_dump(mode="json"))
                session.add(record)
            else:
                record.data = profile.model_dump(mode="json")
                record.updated_at = datetime.now(timezone.utc)
            session.commit()
            return profile

    @application.get(
        "/v1/resumes/master",
        response_model=MasterResumeVersionResponse | None,
        dependencies=[Depends(require_api_token)],
    )
    def get_master_resume() -> MasterResumeVersion | None:
        with session_factory() as session:
            return session.scalar(
                select(MasterResumeVersion).order_by(MasterResumeVersion.created_at.desc()).limit(1)
            )

    @application.get(
        "/v1/resumes/master/versions",
        response_model=list[MasterResumeVersionSummary],
        dependencies=[Depends(require_api_token)],
    )
    def list_master_resume_versions() -> list[MasterResumeVersion]:
        with session_factory() as session:
            return list(
                session.scalars(
                    select(MasterResumeVersion).order_by(MasterResumeVersion.created_at.desc())
                )
            )

    @application.get(
        "/v1/resumes/master/versions/{version_id}",
        response_model=MasterResumeVersionResponse,
        dependencies=[Depends(require_api_token)],
    )
    def get_master_resume_version(version_id: UUID) -> MasterResumeVersion:
        with session_factory() as session:
            version = session.get(MasterResumeVersion, version_id)
            if version is None:
                raise HTTPException(status_code=404, detail="Master resume version not found")
            return version

    @application.post(
        "/v1/resumes/master/versions",
        response_model=MasterResumeVersionResponse,
        status_code=status.HTTP_201_CREATED,
        dependencies=[Depends(require_api_token)],
    )
    def create_master_resume_version(request: MasterResumeCreate) -> MasterResumeVersion:
        version = MasterResumeVersion(
            content=request.content,
            content_sha256=sha256(request.content.encode("utf-8")).hexdigest(),
            change_note=request.change_note,
        )
        with session_factory() as session:
            session.add(version)
            session.commit()
            session.refresh(version)
            return version

    @application.get(
        "/v1/tasks",
        response_model=list[TaskResponse],
        dependencies=[Depends(require_api_token)],
    )
    def list_tasks() -> list[TaskResponse]:
        return _task_call(application.state.task_repository.list)

    @application.post(
        "/v1/tasks",
        response_model=TaskResponse,
        status_code=status.HTTP_201_CREATED,
        dependencies=[Depends(require_api_token)],
    )
    def create_task(task: TaskCreate) -> TaskResponse:
        return _task_call(application.state.task_repository.create, task)

    @application.get(
        "/v1/tasks/{task_id}",
        response_model=TaskResponse,
        dependencies=[Depends(require_api_token)],
    )
    def get_task(task_id: UUID) -> TaskResponse:
        task = _task_call(application.state.task_repository.get, task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found")
        return task

    @application.patch(
        "/v1/tasks/{task_id}",
        response_model=TaskResponse,
        dependencies=[Depends(require_api_token)],
    )
    def update_task(task_id: UUID, changes: TaskUpdate) -> TaskResponse:
        task = _task_call(application.state.task_repository.update, task_id, changes)
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found")
        return task

    return application


def _task_call(operation, *args):
    try:
        return operation(*args)
    except TaskStoreUnavailable as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


def _parse_job_search_request(goal: str) -> JobSearchRequest | None:
    value = goal.strip()
    if not re.match(r"^(?:please\s+)?(?:find|search|look for|show me|discover|run|execute)\b", value, re.IGNORECASE):
        return None
    if not re.search(r"\bjobs?\b|\bjob\s+search\b", value, re.IGNORECASE):
        return None

    location_match = re.search(r"\bjobs?\s+in\s+([^,.!?]+)", value, re.IGNORECASE)
    location = location_match.group(1).strip() if location_match else ""
    if location:
        location = re.split(
            r"\b(?:above|over|at least|minimum(?: match)?(?: score)?|remote|entry[- ]level|fresher|junior|senior|mid[- ]level)\b",
            location,
            maxsplit=1,
            flags=re.IGNORECASE,
        )[0].strip()
    role_match = re.search(
        r"^(?:please\s+)?(?:find|search(?:\s+for)?|look for|show me|discover|run|execute)\s+(.*?)\s+jobs?\b",
        value,
        re.IGNORECASE,
    )
    role = role_match.group(1).strip() if role_match else ""
    role = re.sub(r"\b(?:remote|entry[- ]level|junior|senior|mid[- ]level|fresher)\b", "", role, flags=re.IGNORECASE)
    role = re.sub(r"\b(?:for me|suitable for me)\b", "", role, flags=re.IGNORECASE).strip(" ,")
    role = re.sub(r"\b(?:my|today'?s|today)\b", "", role, flags=re.IGNORECASE).strip(" ,")
    if location:
        role = re.sub(r"\b(?:in|at)\s+" + re.escape(location) + r"$", "", role, flags=re.IGNORECASE).strip()
    experience_match = re.search(r"\b(entry[- ]level|fresher|junior|senior|mid[- ]level)\b", value, re.IGNORECASE)
    score_match = re.search(r"\b(?:above|over|at least|minimum(?: match)?(?: score)?)\s+(\d{1,3})\s*%?", value, re.IGNORECASE)
    return JobSearchRequest(
        role=role,
        location=location,
        remote_preference="remote" if re.search(r"\bremote\b", value, re.IGNORECASE) else "",
        experience_level=experience_match.group(1) if experience_match else "",
        minimum_match_score=min(int(score_match.group(1)), 100) if score_match else 0,
    )


def _run_job_search(session, request: JobSearchRequest) -> JobSearchResponse:
    result = search_jobs(session, request)
    if result.status == "WAITING_FOR_USER":
        summary = f"Search not started: {result.sources[0].error if result.sources else 'Required role information is missing.'}"
    else:
        source_issues = [
            f"{source.source}: {source.error or source.status}"
            for source in result.sources
            if source.status != "success"
        ]
        summary = (
            f"Found {result.total_found} matching jobs; removed {result.duplicates_removed} duplicates. "
            f"Source issues: {'; '.join(source_issues) if source_issues else 'none'}."
        )
    session.add(ActivityRun(
        goal=f"Find {result.query.role or 'jobs'}"
        + (f" in {result.query.location}" if result.query.location else ""),
        agent="Job Search Agent",
        permission_level=1,
        status=result.status,
        summary=summary,
    ))
    session.commit()
    return result


def _action_description(request: LocalActionRequest) -> str:
    if request.action == "run_command":
        return f"Run PowerShell command: {request.command}"
    if request.action == "launch_app":
        return f"Launch app: {request.app_name}"
    return f"{request.action.replace('_', ' ').capitalize()}: {request.path or '.'}"


def _approval_description(request: LocalActionRequest) -> str:
    if request.action == "run_command":
        return f"Run this PowerShell command in the configured workspace:\n{request.command}"
    if request.action == "update_file":
        return f"Overwrite {request.path} with this exact content:\n{request.content}"
    if request.action == "delete_file":
        return f"Delete this file from the configured workspace: {request.path}"
    return _action_description(request)


def _prepare_local_action(application: FastAPI, request: LocalActionRequest) -> LocalActionResponse:
    needs_approval = request.action in {"update_file", "delete_file", "run_command"}
    action_id = uuid4()
    run_id = uuid4()
    with application.state.session_factory() as session:
        run = ActivityRun(
            id=run_id,
            goal=_action_description(request),
            agent="Computer Agent",
            permission_level=4 if needs_approval else 3,
            status="WAITING_FOR_APPROVAL" if needs_approval else "PARTIAL_SUCCESS",
            summary="Waiting for explicit approval." if needs_approval else "Local action started.",
        )
        session.add(run)
        session.flush()
        action = LocalAction(
            id=action_id,
            run_id=run_id,
            action=request.action,
            payload=request.model_dump_json(),
            status="pending_approval" if needs_approval else "running",
            summary="Waiting for explicit approval." if needs_approval else "Local action started.",
        )
        approval = None
        if needs_approval:
            approval = Approval(
                run_id=run_id,
                action_summary=_action_description(request),
                status="pending",
            )
            session.add(approval)
            session.flush()
            action.approval_id = approval.id
        session.add(action)
        session.commit()
        if approval:
            return LocalActionResponse(
                id=action.id,
                action=action.action,
                status=action.status,
                summary=action.summary,
                approval_id=approval.id,
                confirmation=_approval_description(request),
            )
    return _execute_local_action(application, action_id)


def _execute_local_action(application: FastAPI, action_id: UUID) -> LocalActionResponse:
    factory = application.state.session_factory
    with factory() as session:
        action = session.get(LocalAction, action_id)
        if action is None:
            raise HTTPException(status_code=404, detail="Local action not found")
        request = LocalActionRequest.model_validate_json(action.payload)

    try:
        result = application.state.local_tools.execute(request)
    except HTTPException as error:
        with factory() as session:
            action = session.get(LocalAction, action_id)
            run = session.get(ActivityRun, action.run_id) if action else None
            if action:
                action.status = "failed"
                action.summary = f"Action failed: {error.detail}"
                if run:
                    run.status = "FAILED"
                    run.summary = action.summary
                session.commit()
        raise
    except OSError as error:
        with factory() as session:
            action = session.get(LocalAction, action_id)
            run = session.get(ActivityRun, action.run_id) if action else None
            if action:
                action.status = "failed"
                action.summary = "Local action failed due to an operating system error."
                if run:
                    run.status = "FAILED"
                    run.summary = action.summary
                session.commit()
        raise HTTPException(status_code=500, detail="Local action failed due to an operating system error") from error

    if request.action == "run_command" and result["return_code"] != 0:
        action_status = "failed"
        summary = f"Command exited with code {result['return_code']}."
        run_status = "FAILED"
    else:
        action_status = "success"
        summary = f"{request.action.replace('_', ' ').capitalize()} completed successfully."
        run_status = "SUCCESS"
    with factory() as session:
        action = session.get(LocalAction, action_id)
        run = session.get(ActivityRun, action.run_id) if action else None
        if action:
            action.status = action_status
            action.summary = summary
            action.result = json.dumps(result)
            action.updated_at = datetime.now(timezone.utc)
            if run:
                run.status = run_status
                run.summary = summary
            session.commit()
        return LocalActionResponse(
            id=action.id,
            action=action.action,
            status=action.status,
            summary=action.summary,
            result=result,
            approval_id=action.approval_id,
        )


app = create_app()
