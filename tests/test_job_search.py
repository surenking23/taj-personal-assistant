from dataclasses import replace

from jarvis.job_search import RawJob, _location_matches


def sample_job(url="https://jobs.example.test/role/1", source="Fixture"):
    return RawJob(
        company="Example Analytics",
        title="Junior Data Analyst",
        location="Chennai, India",
        work_mode="On-site",
        url=url,
        application_url=url,
        description="Required: SQL and Python. Preferred: Tableau.",
        requirements="Required: SQL and Python. Preferred: Tableau.",
        skills=("SQL", "Python", "Tableau"),
        required_skills=("SQL", "Python"),
        preferred_skills=("Tableau",),
        experience="",
        salary="",
        source=source,
        posted_date="2026-10-01",
    )


def test_search_uses_saved_profile_scores_and_deduplicates(tmp_path, monkeypatch):
    import jarvis.job_search as search

    monkeypatch.setenv("JOB_SEARCH_SOURCES", "arbeitnow,remoteok")
    monkeypatch.setattr(search, "SOURCES", {
        "arbeitnow": lambda: [sample_job()],
        "remoteok": lambda: [sample_job("https://www.jobs.example.test/role/1?ref=remoteok", "RemoteOK")],
    })
    with search_test_client(tmp_path / "jobs.db") as client:
        saved = client.put("/v1/profile", headers=auth_headers(), json={
            "name": "Suren",
            "skills": ["SQL", "Python", "Tableau"],
            "career_target": {
                "primary_role": "Data Analyst",
                "preferred_locations": ["Chennai"],
                "experience_level": "entry-level",
            },
        })
        assert saved.status_code == 200
        result = client.post("/v1/jobs/search", headers=auth_headers(), json={"role": "Data Analyst"})
        assert result.status_code == 200
        body = result.json()
        assert body["status"] == "SUCCESS"
        assert body["total_found"] == 1
        assert body["duplicates_removed"] == 1
        assert body["existing_listings_updated"] == 0
        job = body["jobs"][0]
        assert job["company"] == "Example Analytics"
        assert job["required_skills"] == ["SQL", "Python"]
        assert job["preferred_skills"] == ["Tableau"]
        assert job["match_score"] >= 85
        assert client.get("/v1/jobs", headers=auth_headers()).json()[0]["id"] == job["id"]
        repeated = client.post("/v1/jobs/search", headers=auth_headers(), json={"role": "Data Analyst"})
        assert repeated.json()["duplicates_removed"] == 1
        assert repeated.json()["existing_listings_updated"] == 1
        activity = client.get("/v1/activity", headers=auth_headers()).json()
        assert activity[0]["agent"] == "Job Search Agent"
        assert activity[0]["status"] == "SUCCESS"


def test_search_reports_each_source_failure_and_missing_configuration(tmp_path, monkeypatch):
    import jarvis.job_search as search

    monkeypatch.setenv("JOB_SEARCH_SOURCES", "arbeitnow,remoteok")
    monkeypatch.setattr(search, "SOURCES", {
        "arbeitnow": lambda: (_ for _ in ()).throw(TimeoutError("provider timeout")),
        "remoteok": lambda: [sample_job()],
    })
    with search_test_client(tmp_path / "source-errors.db") as client:
        result = client.post("/v1/jobs/search", headers=auth_headers(), json={"role": "Data Analyst"})
        assert result.status_code == 200
        body = result.json()
        assert body["status"] == "PARTIAL_SUCCESS"
        assert {source["source"]: source["status"] for source in body["sources"]} == {
            "arbeitnow": "unavailable",
            "remoteok": "success",
        }
        assert "provider timeout" in body["sources"][0]["error"]

    monkeypatch.setenv("JOB_SEARCH_SOURCES", "")
    with search_test_client(tmp_path / "unconfigured.db") as client:
        result = client.post("/v1/jobs/search", headers=auth_headers(), json={"role": "Data Analyst"})
        assert result.status_code == 200
        assert result.json()["status"] == "NEEDS_CONFIGURATION"


def test_search_waits_for_role_when_profile_has_no_career_target(tmp_path, monkeypatch):
    import jarvis.job_search as search

    calls = []
    monkeypatch.setenv("JOB_SEARCH_SOURCES", "arbeitnow")
    monkeypatch.setattr(search, "SOURCES", {"arbeitnow": lambda: calls.append("called") or [sample_job()]})
    class MustNotRunRouter:
        def classify(self, goal, history=None):
            raise AssertionError("Missing career criteria should be identified before chat.")

        def status(self):
            raise AssertionError("Missing career criteria should not query model status.")

    with search_test_client(tmp_path / "missing-role.db", model_router=MustNotRunRouter()) as client:
        response = client.post("/v1/jobs/search", headers=auth_headers(), json={})
        assert response.status_code == 200
        assert response.json()["status"] == "WAITING_FOR_USER"
        assert "target role" in response.json()["sources"][0]["error"]
        assert calls == []
        chat = client.post(
            "/v1/assistant/chat",
            headers=auth_headers(),
            json={"goal": "Find jobs"},
        )
        assert chat.status_code == 200
        assert chat.json()["status"] == "WAITING_FOR_USER"
        assert "target role" in chat.json()["response"]


def test_india_remote_preference_does_not_treat_unspecified_remote_as_india():
    worldwide_remote = replace(sample_job(), location="Remote", work_mode="Remote")
    india_remote = replace(sample_job(), location="Remote - India", work_mode="Remote")
    india_city = replace(sample_job(), location="Chennai")
    preferences = ["India", "Chennai", "Bangalore", "Remote India"]
    assert not _location_matches(preferences, worldwide_remote)
    assert _location_matches(preferences, india_remote)
    assert _location_matches(preferences, india_city)
    assert _location_matches(["United Kingdom"], replace(sample_job(), location="London, United Kingdom"))


def test_saved_secondary_target_roles_are_included_when_role_is_blank(tmp_path, monkeypatch):
    import jarvis.job_search as search

    monkeypatch.setenv("JOB_SEARCH_SOURCES", "arbeitnow")
    bi_role = replace(
        sample_job("https://jobs.example.test/role/bi"),
        company="Business Intelligence Co",
        title="BI Analyst",
    )
    monkeypatch.setattr(search, "SOURCES", {"arbeitnow": lambda: [sample_job(), bi_role]})
    with search_test_client(tmp_path / "secondary-roles.db") as client:
        client.put("/v1/profile", headers=auth_headers(), json={
            "career_target": {
                "primary_role": "Data Analyst",
                "secondary_roles": ["BI Analyst"],
            },
        })
        result = client.post("/v1/jobs/search", headers=auth_headers(), json={})
        assert result.status_code == 200
        assert result.json()["query"]["roles"] == ["Data Analyst", "BI Analyst"]
        assert {job["title"] for job in result.json()["jobs"]} == {"Junior Data Analyst", "BI Analyst"}


def test_saved_jobs_hide_old_irrelevant_listings_and_apply_profile_roles(tmp_path, monkeypatch):
    import jarvis.job_search as search

    irrelevant = replace(
        sample_job("https://jobs.example.test/role/support"),
        title="Customer Support Specialist",
        company="Example Support",
    )
    monkeypatch.setenv("JOB_SEARCH_SOURCES", "arbeitnow")
    monkeypatch.setattr(search, "SOURCES", {"arbeitnow": lambda: [sample_job(), irrelevant]})
    with search_test_client(tmp_path / "saved-filter.db") as client:
        client.put("/v1/profile", headers=auth_headers(), json={
            "career_target": {"primary_role": "Data Analyst"},
            "skills": ["SQL", "Python"],
        })
        client.post("/v1/jobs/search", headers=auth_headers(), json={"role": "Data Analyst"})
        saved = client.get("/v1/jobs", headers=auth_headers()).json()
        assert [job["title"] for job in saved] == ["Junior Data Analyst"]
        assert saved[0]["date_found"]


def test_search_deprioritizes_sales_and_customer_support_titles(tmp_path, monkeypatch):
    import jarvis.job_search as search

    sales = replace(sample_job("https://jobs.example.test/role/sales"), title="Sales Data Analyst")
    support = replace(sample_job("https://jobs.example.test/role/support"), title="Customer Support Specialist")
    monkeypatch.setenv("JOB_SEARCH_SOURCES", "arbeitnow")
    monkeypatch.setattr(search, "SOURCES", {"arbeitnow": lambda: [sample_job(), sales, support]})
    with search_test_client(tmp_path / "excluded-roles.db") as client:
        response = client.post(
            "/v1/jobs/search",
            headers=auth_headers(),
            json={"role": "Data Analyst"},
        )
        assert [job["title"] for job in response.json()["jobs"]] == ["Junior Data Analyst"]


def test_natural_language_job_search_runs_before_chat_model(tmp_path, monkeypatch):
    import jarvis.job_search as search

    class MustNotRunRouter:
        def classify(self, goal, history=None):
            raise AssertionError("Job-search intent must be routed to the search tool before the model.")

        def status(self):
            raise AssertionError("Job search does not need model status.")

    monkeypatch.setenv("JOB_SEARCH_SOURCES", "arbeitnow")
    monkeypatch.setattr(search, "SOURCES", {"arbeitnow": lambda: [sample_job()]})
    with search_test_client(tmp_path / "chat-search.db", model_router=MustNotRunRouter()) as client:
        client.put("/v1/profile", headers=auth_headers(), json={
            "skills": ["SQL", "Python", "Tableau"],
            "career_target": {
                "primary_role": "Data Analyst",
                "preferred_locations": ["Chennai"],
                "experience_level": "entry-level",
            },
        })
        response = client.post(
            "/v1/assistant/chat",
            headers=auth_headers(),
            json={"goal": "Find entry-level Data Analyst jobs in Chennai above 85% match"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "SUCCESS"
        assert body["job_search"]["query"]["role"] == "Data Analyst"
        assert body["job_search"]["query"]["location"] == "Chennai"
        assert body["job_search"]["query"]["minimum_match_score"] == 85
        assert len(body["job_search"]["jobs"]) == 1


def test_run_my_job_search_uses_saved_target_roles(tmp_path, monkeypatch):
    import jarvis.job_search as search

    monkeypatch.setenv("JOB_SEARCH_SOURCES", "arbeitnow")
    monkeypatch.setattr(search, "SOURCES", {"arbeitnow": lambda: [sample_job()]})
    with search_test_client(tmp_path / "daily-search.db") as client:
        client.put("/v1/profile", headers=auth_headers(), json={
            "career_target": {
                "primary_role": "Data Analyst",
                "secondary_roles": ["BI Analyst"],
                "experience_level": "fresher",
            },
        })
        response = client.post(
            "/v1/assistant/chat",
            headers=auth_headers(),
            json={"goal": "Run my job search"},
        )
        assert response.status_code == 200
        assert response.json()["status"] == "SUCCESS"
        assert response.json()["job_search"]["query"]["roles"] == ["Data Analyst", "BI Analyst"]


def test_chat_parses_today_search_using_saved_profile(tmp_path, monkeypatch):
    import jarvis.job_search as search

    monkeypatch.setenv("JOB_SEARCH_SOURCES", "arbeitnow")
    monkeypatch.setattr(search, "SOURCES", {"arbeitnow": lambda: [sample_job()]})
    with search_test_client(tmp_path / "todays-search.db") as client:
        client.put("/v1/profile", headers=auth_headers(), json={
            "career_target": {"primary_role": "Data Analyst"},
        })
        response = client.post(
            "/v1/assistant/chat",
            headers=auth_headers(),
            json={"goal": "Find today's jobs"},
        )
        assert response.status_code == 200
        assert response.json()["job_search"]["query"]["roles"] == ["Data Analyst"]


def test_search_and_apply_request_searches_but_does_not_claim_submission(tmp_path, monkeypatch):
    import jarvis.job_search as search

    monkeypatch.setenv("JOB_SEARCH_SOURCES", "arbeitnow")
    monkeypatch.setattr(search, "SOURCES", {"arbeitnow": lambda: [sample_job()]})
    with search_test_client(tmp_path / "search-and-apply.db") as client:
        client.put("/v1/profile", headers=auth_headers(), json={
            "skills": ["SQL", "Python"],
            "career_target": {"primary_role": "Data Analyst"},
        })
        response = client.post(
            "/v1/assistant/chat",
            headers=auth_headers(),
            json={"goal": "Find Data Analyst jobs and apply automatically"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "PARTIAL_SUCCESS"
        assert body["job_search"]["total_found"] == 1
        assert "no application was prepared or submitted" in body["response"]
        assert body["action"] is None


def search_test_client(path, model_router=None):
    from fastapi.testclient import TestClient
    from jarvis.main import create_app

    application = create_app(
        database_url=f"sqlite:///{path}",
        api_token="test-token",
        workspace=path.parent,
        model_router=model_router,
    )
    return TestClient(application)


def auth_headers():
    return {"Authorization": "Bearer test-token"}
