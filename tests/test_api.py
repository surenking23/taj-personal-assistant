from datetime import datetime, timezone
from hashlib import sha256
from uuid import uuid4

from fastapi.testclient import TestClient

from jarvis.agents.openai import ModelStatus
from jarvis.main import create_app
from jarvis.schemas import LocalActionRequest, OllamaIntent, TaskResponse


class MemoryTaskRepository:
    def __init__(self):
        self.tasks = {}

    def create(self, task):
        record = TaskResponse(
            id=uuid4(),
            title=task.title,
            description=task.description,
            status="pending",
            due_at=task.due_at,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        self.tasks[record.id] = record
        return record

    def list(self):
        return list(self.tasks.values())

    def get(self, task_id):
        return self.tasks.get(task_id)

    def update(self, task_id, changes):
        task = self.tasks.get(task_id)
        if task is None:
            return None
        updated = task.model_copy(update={**changes.model_dump(exclude_unset=True), "updated_at": datetime.now(timezone.utc)})
        self.tasks[task_id] = updated
        return updated

    def delete(self, task_id):
        return self.tasks.pop(task_id, None) is not None


def make_client(database_path, workspace=None, model_router=None):
    application = create_app(
        database_url=f"sqlite:///{database_path}",
        api_token="test-token",
        workspace=workspace or database_path.parent,
        model_router=model_router,
    )
    application.state.task_repository = MemoryTaskRepository()
    return TestClient(application)


def auth_headers():
    return {"Authorization": "Bearer test-token"}


def test_command_routes_and_high_impact_waits_for_approval(tmp_path):
    with make_client(tmp_path / "commands.db") as client:
        safe = client.post("/v1/commands", headers=auth_headers(), json={"goal": "Research Python testing"})
        assert safe.status_code == 200
        assert safe.json()["status"] == "PARTIAL_SUCCESS"
        assert safe.json()["agent"] == "Research Agent"

        risky = client.post("/v1/commands", headers=auth_headers(), json={"goal": "Send an email to my manager"})
        assert risky.status_code == 200
        assert risky.json()["status"] == "WAITING_FOR_APPROVAL"
        approval_id = risky.json()["approval_id"]

        listed = client.get("/v1/approvals?pending_only=true", headers=auth_headers())
        assert len(listed.json()) == 1
        decided = client.post(
            f"/v1/approvals/{approval_id}/decision",
            headers=auth_headers(),
            json={"approved": True, "note": "Reviewed"},
        )
        assert decided.status_code == 200
        assert decided.json()["status"] == "approved"
        activity = client.get("/v1/activity", headers=auth_headers()).json()
        approved_run = next(item for item in activity if item["id"] == risky.json()["run_id"])
        assert approved_run["status"] == "PARTIAL_SUCCESS"
        assert "not yet been executed" in approved_run["summary"]


def test_memory_is_hidden_until_approved(tmp_path):
    with make_client(tmp_path / "memory.db") as client:
        created = client.post(
            "/v1/memory",
            headers=auth_headers(),
            json={"category": "career", "content": "Interested in backend engineering"},
        )
        assert created.status_code == 201
        assert created.json()["approved"] is False
        assert client.get("/v1/memory", headers=auth_headers()).json() == []

        approved = client.post(
            f"/v1/memory/{created.json()['id']}/approve",
            headers=auth_headers(),
        )
        assert approved.status_code == 200
        assert approved.json()["approved"] is True
        assert len(client.get("/v1/memory", headers=auth_headers()).json()) == 1


def test_career_profile_is_editable_and_requires_authentication(tmp_path):
    with make_client(tmp_path / "profile.db") as client:
        assert client.get("/v1/profile", headers=auth_headers()).json() == {
            "name": "",
            "email": "",
            "phone": "",
            "location": "",
            "linkedin_url": "",
            "github_url": "",
            "portfolio_url": "",
            "professional_headline": "",
            "education": {
                "degree": "",
                "college": "",
                "university": "",
                "graduation_year": "",
                "relevant_coursework": [],
            },
            "career_target": {
                "primary_role": "",
                "secondary_roles": [],
                "experience_level": "",
                "preferred_industries": [],
                "preferred_locations": [],
                "work_authorization_countries": [],
                "work_mode": "",
                "salary_expectations": "",
                "relocation_preference": "",
                "notice_period": "",
            },
            "skills": [],
            "projects": [],
        }
        profile = {
            "name": "Suren",
            "email": "suren@example.test",
            "education": {"degree": "BSc", "relevant_coursework": ["Statistics"]},
            "career_target": {
                "primary_role": "Data Analyst",
                "secondary_roles": ["BI Analyst"],
                "work_mode": "Remote",
            },
            "skills": ["SQL", "Python"],
            "projects": [{
                "name": "E-Commerce Sales Analytics",
                "summary": "Sales and profit analysis.",
                "tools": ["Python", "Power BI"],
                "verified_metrics": ["Approximately 5,000 orders/customers in the project dataset"],
                "repository_url": "https://github.com/surenking23/E-Commerce-Sales-Analytics",
            }],
        }
        saved = client.put("/v1/profile", headers=auth_headers(), json=profile)
        assert saved.status_code == 200
        assert saved.json()["name"] == "Suren"
        assert saved.json()["career_target"]["primary_role"] == "Data Analyst"
        assert saved.json()["skills"] == ["SQL", "Python"]
        assert saved.json()["projects"][0]["name"] == "E-Commerce Sales Analytics"
        assert saved.json()["projects"][0]["verified_metrics"] == [
            "Approximately 5,000 orders/customers in the project dataset"
        ]
        assert client.get("/v1/profile", headers=auth_headers()).json() == saved.json()
        assert client.get("/v1/profile").status_code == 401
        assert client.put("/v1/profile", headers=auth_headers(), json={"skills": [1]}).status_code == 422


def test_master_resume_versions_are_append_only_and_verified(tmp_path):
    with make_client(tmp_path / "resume.db") as client:
        assert client.get("/v1/resumes/master", headers=auth_headers()).json() is None
        first_content = "Resume v1\nSQL, Python"
        first = client.post(
            "/v1/resumes/master/versions",
            headers=auth_headers(),
            json={"content": first_content, "change_note": "Initial source resume"},
        )
        assert first.status_code == 201
        first_version = first.json()
        assert first_version["content"] == first_content
        assert first_version["content_sha256"] == sha256(first_content.encode("utf-8")).hexdigest()

        second_content = f"{first_content}\nPower BI"
        second = client.post(
            "/v1/resumes/master/versions",
            headers=auth_headers(),
            json={"content": second_content},
        )
        assert second.status_code == 201
        assert client.get("/v1/resumes/master", headers=auth_headers()).json()["id"] == second.json()["id"]
        assert client.get(
            f"/v1/resumes/master/versions/{first_version['id']}",
            headers=auth_headers(),
        ).json()["content"] == first_content
        versions = client.get("/v1/resumes/master/versions", headers=auth_headers()).json()
        assert {version["id"] for version in versions} == {first_version["id"], second.json()["id"]}
        assert client.post("/v1/resumes/master/versions", headers=auth_headers(), json={"content": ""}).status_code == 422
        assert client.post("/v1/resumes/master/versions", json={"content": "private"}).status_code == 401


def test_authentication_is_required(tmp_path):
    with make_client(tmp_path / "auth.db") as client:
        assert client.get("/v1/activity").status_code == 401
        assert client.get("/v1/activity", headers={"Authorization": "Bearer wrong"}).status_code == 403


def test_task_endpoints_use_repository_contract(tmp_path):
    with make_client(tmp_path / "tasks.db") as client:
        created = client.post(
            "/v1/tasks",
            headers=auth_headers(),
            json={"title": "Review agent architecture"},
        )
        assert created.status_code == 201
        task_id = created.json()["id"]
        updated = client.patch(
            f"/v1/tasks/{task_id}",
            headers=auth_headers(),
            json={"status": "done"},
        )
        assert updated.status_code == 200
        assert updated.json()["status"] == "done"
        assert client.get(f"/v1/tasks/{task_id}", headers=auth_headers()).status_code == 200


def test_local_file_actions_are_scoped_to_workspace(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    with make_client(tmp_path / "local.db", workspace) as client:
        listed = client.post(
            "/v1/assistant/actions",
            headers=auth_headers(),
            json={"action": "list_files", "path": "."},
        )
        assert listed.status_code == 200
        assert listed.json()["status"] == "success"

        created = client.post(
            "/v1/assistant/actions",
            headers=auth_headers(),
            json={"action": "create_file", "path": "notes.txt", "content": "Remember this"},
        )
        assert created.status_code == 200
        assert (workspace / "notes.txt").read_text(encoding="utf-8") == "Remember this"
        read = client.post(
            "/v1/assistant/actions",
            headers=auth_headers(),
            json={"action": "read_file", "path": "notes.txt"},
        )
        assert read.json()["result"]["content"] == "Remember this"

        escaped = client.post(
            "/v1/assistant/actions",
            headers=auth_headers(),
            json={"action": "read_file", "path": "..\\outside.txt"},
        )
        assert escaped.status_code == 403


def test_destructive_action_requires_approval_and_separate_execution(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "notes.txt").write_text("keep", encoding="utf-8")
    with make_client(tmp_path / "approval.db", workspace) as client:
        proposed = client.post(
            "/v1/assistant/actions",
            headers=auth_headers(),
            json={"action": "delete_file", "path": "notes.txt"},
        )
        assert proposed.status_code == 200
        action = proposed.json()
        assert action["status"] == "pending_approval"
        assert action["confirmation"] == "Delete this file from the configured workspace: notes.txt"
        assert (workspace / "notes.txt").exists()

        premature = client.post(
            f"/v1/assistant/actions/{action['id']}/execute",
            headers=auth_headers(),
        )
        assert premature.status_code == 409
        decision = client.post(
            f"/v1/approvals/{action['approval_id']}/decision",
            headers=auth_headers(),
            json={"approved": True},
        )
        assert decision.status_code == 200
        assert (workspace / "notes.txt").exists()

        result = client.post(
            f"/v1/assistant/actions/{action['id']}/execute",
            headers=auth_headers(),
        )
        assert result.status_code == 200
        assert result.json()["status"] == "success"
        assert not (workspace / "notes.txt").exists()
        assert client.post(
            f"/v1/assistant/actions/{action['id']}/execute",
            headers=auth_headers(),
        ).status_code == 409


def test_chat_page_is_served():
    application = create_app(database_url="sqlite://", api_token="test-token")
    with TestClient(application) as client:
        response = client.get("/")
        assert response.status_code == 200
        assert "TAJ" in response.text
        assert client.get("/openapi.json").json()["info"]["title"] == "Taj Personal Assistant API"


def test_chat_routes_model_intent_through_approval_gate(tmp_path):
    class FakeRouter:
        def classify(self, goal, history=None):
            assert goal == "Please delete notes"
            assert history == []
            return OllamaIntent(
                decision="action",
                action=LocalActionRequest(action="delete_file", path="notes.txt"),
            )

        def status(self):
            return ModelStatus(configured=True, reachable=True, model="test-model", model_available=True)

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "notes.txt").write_text("keep", encoding="utf-8")
    with make_client(tmp_path / "chat.db", workspace, FakeRouter()) as client:
        state = client.get("/v1/assistant/status", headers=auth_headers())
        assert state.status_code == 200
        assert state.json()["model_available"] is True

        response = client.post(
            "/v1/assistant/chat",
            headers=auth_headers(),
            json={"goal": "Please delete notes", "history": []},
        )
        assert response.status_code == 200
        assert response.json()["status"] == "WAITING_FOR_APPROVAL"
        assert response.json()["action"]["approval_id"]
        assert "Delete this file" in response.json()["action"]["confirmation"]
        assert (workspace / "notes.txt").exists()


def test_chat_reports_missing_openai_configuration(tmp_path):
    class UnconfiguredRouter:
        def classify(self, goal, history=None):
            from jarvis.agents.model_errors import ModelNotConfigured

            raise ModelNotConfigured("Sign in to GitHub Copilot CLI")

        def status(self):
            return ModelStatus(False, True, "gpt-5", False)

    with make_client(tmp_path / "offline.db", model_router=UnconfiguredRouter()) as client:
        response = client.post(
            "/v1/assistant/chat",
            headers=auth_headers(),
            json={"goal": "Please do something"},
        )
        assert response.status_code == 503
        assert "GitHub Copilot CLI" in response.json()["detail"]
