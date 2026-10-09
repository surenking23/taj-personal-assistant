import html
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.error import URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from jarvis.models import CareerProfileRecord, JobListing, MasterResumeVersion


SKILL_TERMS = (
    "SQL", "SELECT", "WHERE", "JOIN", "GROUP BY", "HAVING", "ORDER BY",
    "CASE WHEN", "Aggregations", "Subqueries", "CTEs", "Window Functions",
    "Views", "Data Extraction", "Python", "Pandas", "NumPy", "Matplotlib",
    "Seaborn", "Jupyter Notebook", "Power BI", "DAX", "Power Query",
    "Data Modeling", "Dashboard Development", "KPI Reporting",
    "Data Visualization", "Power BI Service", "Excel", "Pivot Tables",
    "XLOOKUP", "SUMIFS", "Charts", "Data Validation", "Statistics",
    "Exploratory Data Analysis", "Descriptive Statistics", "Correlation Analysis",
    "Hypothesis Testing", "Data Cleaning", "Data Transformation",
    "Data Quality Checks", "Insight Generation", "KPI Analysis", "Business Analysis",
    "Data Storytelling", "Tableau", "MySQL", "MySQL Workbench", "PostgreSQL",
    "Git", "GitHub", "Generative AI", "Prompt Engineering", "AI-Assisted Analysis",
    "Automation", "Profitability Analysis", "Customer Segmentation", "Discount Impact",
    "Repeat Purchase Analysis", "Delivery Analysis", "Sales Trends", "Risk Analysis",
    "Banking Analytics", "E-commerce Analytics", "R", "Machine Learning", "Azure",
    "AWS", "Looker", "ETL", "Spark", "Java", "JavaScript", "Salesforce",
)


class JobSearchRequest(BaseModel):
    role: str = Field(default="", max_length=240)
    roles: list[str] = Field(default_factory=list, max_length=50)
    location: str = Field(default="", max_length=240)
    location_preferences: list[str] = Field(default_factory=list, max_length=50)
    remote_preference: str = Field(default="", max_length=80)
    experience_level: str = Field(default="", max_length=100)
    keywords: list[str] = Field(default_factory=list, max_length=50)
    minimum_match_score: int = Field(default=0, ge=0, le=100)
    company: str = Field(default="", max_length=240)
    salary: str = Field(default="", max_length=240)
    limit: int = Field(default=50, ge=1, le=100)


class JobResponse(BaseModel):
    id: str
    company: str
    title: str
    location: str
    work_mode: str
    url: str
    application_url: str
    description: str
    requirements: str
    skills: list[str]
    required_skills: list[str]
    preferred_skills: list[str]
    experience: str
    salary: str
    source: str
    posted_date: str
    date_found: str
    match_score: int
    match_breakdown: dict[str, int]


class SourceReport(BaseModel):
    source: str
    status: str
    jobs_found: int = 0
    error: str | None = None


class JobSearchResponse(BaseModel):
    status: str
    query: JobSearchRequest
    total_found: int
    duplicates_removed: int
    existing_listings_updated: int
    jobs: list[JobResponse]
    sources: list[SourceReport]


@dataclass(frozen=True)
class RawJob:
    company: str
    title: str
    location: str
    work_mode: str
    url: str
    application_url: str
    description: str
    requirements: str
    skills: tuple[str, ...]
    required_skills: tuple[str, ...]
    preferred_skills: tuple[str, ...]
    experience: str
    salary: str
    source: str
    posted_date: str


def configured_sources() -> list[str]:
    raw = os.getenv("JOB_SEARCH_SOURCES", "arbeitnow,remoteok")
    allowed = {"arbeitnow", "remoteok"}
    return [source.strip().casefold() for source in raw.split(",") if source.strip().casefold() in allowed]


def _fetch_json(url: str) -> object:
    request = Request(url, headers={
        "Accept": "application/json",
        "User-Agent": "TajPersonalCareerAgent/0.1 (local job discovery)",
    })
    with urlopen(request, timeout=15) as response:
        if response.status < 200 or response.status >= 300:
            raise URLError(f"HTTP {response.status}")
        return json.loads(response.read(5_000_001).decode("utf-8"))


def _plain_text(value: str) -> str:
    decoded = html.unescape(value or "")
    decoded = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", "", decoded, flags=re.IGNORECASE | re.DOTALL)
    decoded = re.sub(r"<\s*(?:br|/p|/div|/li|/h[1-6])\b[^>]*>", "\n", decoded, flags=re.IGNORECASE)
    lines = [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", line)).strip() for line in decoded.splitlines()]
    return "\n".join(line for line in lines if line)


def _source_text(value: object) -> str:
    text = str(value or "")
    if any(marker in text for marker in ("Ã", "Â", "Ø", "Ù")):
        try:
            return text.encode("latin-1").decode("utf-8")
        except UnicodeError:
            return text
    return text


def _experience(text: str) -> str:
    match = re.search(r"\b(\d+\s*(?:-|to)\s*\d+|\d+\+?)\s+years?(?:\s+of\s+experience)?\b", text, re.IGNORECASE)
    return match.group(0) if match else ""


def _experience_match(level: str, raw: RawJob) -> int:
    preference = level.casefold()
    job_text = f"{raw.title} {raw.description[:3000]}".casefold()
    entry_preference = any(term in preference for term in ("entry", "fresher", "junior", "graduate"))
    senior_preference = any(term in preference for term in ("senior", "lead", "principal"))
    years = raw.experience or _experience(job_text)
    year_range = re.search(r"(\d+)\s*(?:-|to)\s*(\d+)\s+years?", years, re.IGNORECASE)
    single_years = re.search(r"(\d+)\+?\s+years?", years, re.IGNORECASE)
    minimum_years = int(year_range.group(1)) if year_range else int(single_years.group(1)) if single_years else None
    if minimum_years is not None:
        if entry_preference:
            return 100 if minimum_years <= 2 else 0
        if senior_preference:
            return 100 if minimum_years >= 5 else 50
        if "mid" in preference:
            return 100 if 2 <= minimum_years <= 5 else 50
        return 50
    entry_job = any(term in job_text for term in ("entry level", "entry-level", "junior", "graduate", "fresher"))
    senior_job = any(term in job_text for term in ("senior", "staff", "principal", "lead"))
    if entry_preference:
        return 100 if entry_job else 0 if senior_job else 50
    if senior_preference:
        return 100 if senior_job else 0 if entry_job else 50
    if "mid" in preference:
        return 0 if entry_job or senior_job else 50
    return 50


def _date(value: object) -> str:
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc).date().isoformat()
    if isinstance(value, str):
        return value[:10]
    return ""


def _work_modes(value: str) -> set[str]:
    normalized = value.casefold()
    modes = set()
    if "remote" in normalized:
        modes.add("remote")
    if "hybrid" in normalized:
        modes.add("hybrid")
    if any(term in normalized for term in ("onsite", "on-site", "office")):
        modes.add("on-site")
    return modes


def _location_matches(preferences: list[str], raw: RawJob) -> bool:
    actual = _tokens(raw.location)
    for preference in preferences:
        tokens = _tokens(preference)
        place_tokens = tokens - {"india", "remote"}
        if place_tokens & actual:
            return True
        if "india" in tokens and "remote" in tokens and "india" in actual:
            return True
        if tokens == {"remote"} and raw.work_mode.casefold() == "remote":
            return True
    return False


def _skills(text: str) -> tuple[list[str], list[str]]:
    required: list[str] = []
    preferred: list[str] = []
    optional_context = False
    for line in re.split(r"[\n.!?;]+", text):
        normalized = line.casefold()
        if any(word in normalized for word in ("preferred", "nice to have", "nice-to-have", "bonus", "desirable", "optional")):
            optional_context = True
        elif any(word in normalized for word in ("required", "requirements", "must have", "qualifications")):
            optional_context = False
        for skill in SKILL_TERMS:
            pattern = rf"(?<![a-z0-9]){re.escape(skill.casefold())}(?![a-z0-9])"
            destination = preferred if optional_context else required
            if re.search(pattern, normalized) and skill not in destination:
                destination.append(skill)
    return required, preferred


def _arbeitnow() -> list[RawJob]:
    payload = _fetch_json("https://www.arbeitnow.com/api/job-board-api")
    records = payload.get("data", []) if isinstance(payload, dict) else []
    results: list[RawJob] = []
    for item in records:
        if not isinstance(item, dict):
            continue
        description = _plain_text(_source_text(item.get("description")))
        tags = item.get("tags") if isinstance(item.get("tags"), list) else []
        tag_skills = [str(tag).strip() for tag in tags if isinstance(tag, str) and tag.strip()]
        required, preferred = _skills(description)
        for skill in tag_skills:
            if skill.casefold() in {term.casefold() for term in SKILL_TERMS} and skill not in required:
                required.append(next(term for term in SKILL_TERMS if term.casefold() == skill.casefold()))
        url = str(item.get("url") or "")
        results.append(RawJob(
            company=_source_text(item.get("company_name")) or "Unknown company",
            title=_source_text(item.get("title")),
            location=_source_text(item.get("location")),
            work_mode=(
                "Remote" if item.get("remote") else
                "Hybrid" if "hybrid" in description.casefold() else
                "On-site"
            ),
            url=url,
            application_url=url,
            description=description,
            requirements=" ".join(required + preferred),
            skills=tuple(dict.fromkeys(required + preferred)),
            required_skills=tuple(required),
            preferred_skills=tuple(preferred),
            experience=_experience(description),
            salary="",
            source="Arbeitnow",
            posted_date=_date(item.get("created_at")),
        ))
    return results


def _remoteok() -> list[RawJob]:
    payload = _fetch_json("https://remoteok.com/api")
    records = payload[1:] if isinstance(payload, list) else []
    results: list[RawJob] = []
    for item in records:
        if not isinstance(item, dict):
            continue
        description = _plain_text(_source_text(item.get("description")))
        tags = item.get("tags") if isinstance(item.get("tags"), list) else []
        tag_skills = [str(tag).strip() for tag in tags if isinstance(tag, str) and tag.strip()]
        required, preferred = _skills(description)
        for skill in tag_skills:
            known = next((term for term in SKILL_TERMS if term.casefold() == skill.casefold()), None)
            if known and known not in required:
                required.append(known)
        url = str(item.get("url") or "")
        application_url = str(item.get("apply_url") or url)
        results.append(RawJob(
            company=_source_text(item.get("company")) or "Unknown company",
            title=_source_text(item.get("position")),
            location=_source_text(item.get("location")) or "Remote",
            work_mode="Remote",
            url=url,
            application_url=application_url,
            description=description,
            requirements=" ".join(required + preferred),
            skills=tuple(dict.fromkeys(required + preferred)),
            required_skills=tuple(required),
            preferred_skills=tuple(preferred),
            experience=_experience(description),
            salary=" ".join(part for part in (str(item.get("salary_min") or ""), str(item.get("salary_max") or "")) if part),
            source="RemoteOK",
            posted_date=_date(item.get("date")),
        ))
    return results


SOURCES = {"arbeitnow": _arbeitnow, "remoteok": _remoteok}


def _canonical_url(url: str) -> str:
    parts = urlsplit(url.strip())
    if parts.scheme.casefold() not in {"http", "https"} or not parts.netloc:
        return ""
    host = parts.netloc.casefold().removeprefix("www.")
    path = parts.path.rstrip("/")
    return urlunsplit((parts.scheme.casefold(), host, path, "", "")).casefold()


def _tokens(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9+#.]+", value.casefold()))


def _score(raw: RawJob, request: JobSearchRequest, profile: dict, resume_text: str) -> tuple[int, dict[str, int]]:
    profile_target = profile.get("career_target") if isinstance(profile.get("career_target"), dict) else {}
    breakdown: dict[str, int] = {}
    roles = request.roles or ([request.role] if request.role else [])
    role_scores = []
    for role in roles:
        role_tokens = _tokens(role) - {"junior", "senior", "entry", "level", "focused"}
        if role_tokens:
            title_tokens = _tokens(raw.title)
            role_scores.append(round(100 * len(role_tokens & title_tokens) / len(role_tokens)))
    if role_scores:
        breakdown["role"] = max(role_scores)
    location_preferences = request.location_preferences or ([request.location] if request.location else [])
    remote = request.remote_preference or str(profile_target.get("work_mode") or "")
    experience = request.experience_level or str(profile_target.get("experience_level") or "")
    profile_skills = {str(skill).casefold() for skill in profile.get("skills", []) if isinstance(skill, str)}
    resume_text_lower = resume_text.casefold()
    profile_skills.update(term.casefold() for term in SKILL_TERMS if re.search(
        rf"(?<![a-z0-9]){re.escape(term.casefold())}(?![a-z0-9])", resume_text_lower
    ))
    required = {skill.casefold() for skill in raw.required_skills}
    preferred = {skill.casefold() for skill in raw.preferred_skills}
    requested_keywords = {word.casefold() for word in request.keywords}
    required.update(requested_keywords)
    if required or preferred:
        skill_weights = {skill: 2 for skill in required} | {skill: 1 for skill in preferred - required}
        total_weight = sum(skill_weights.values())
        matched_weight = sum(weight for skill, weight in skill_weights.items() if skill in profile_skills)
        breakdown["skills"] = round(100 * matched_weight / total_weight) if total_weight else 0
    if location_preferences:
        matching_location = _location_matches(location_preferences, raw)
        breakdown["location"] = 100 if matching_location else 0
    if remote:
        allowed_modes = _work_modes(remote)
        if len(allowed_modes) == 1:
            breakdown["work_mode"] = 100 if raw.work_mode.casefold() in allowed_modes else 0
    if experience:
        breakdown["experience"] = _experience_match(experience, raw)
    weights = {"skills": 60, "role": 25, "location": 5, "work_mode": 5, "experience": 5}
    score = round(sum(breakdown[key] * weights[key] for key in breakdown) / 100)
    return score, breakdown


def _matches_filters(raw: RawJob, request: JobSearchRequest) -> bool:
    title = raw.title.casefold()
    if re.search(r"\b(sales|customer service|customer support|business development|call center)\b", title):
        return False
    roles = request.roles or ([request.role] if request.role else [])
    if roles:
        title_tokens = _tokens(raw.title)
        if not any(
            role_tokens and len(role_tokens & title_tokens) / len(role_tokens) >= 0.5
            for role in roles
            for role_tokens in [_tokens(role) - {"junior", "senior", "entry", "level", "focused"}]
        ):
            return False
    locations = request.location_preferences or ([request.location] if request.location else [])
    if locations and not _location_matches(locations, raw):
        return False
    if request.company and request.company.casefold() not in raw.company.casefold():
        return False
    allowed_modes = _work_modes(request.remote_preference)
    if len(allowed_modes) == 1 and raw.work_mode.casefold() not in allowed_modes:
        return False
    if request.salary and request.salary.casefold() not in raw.salary.casefold():
        return False
    searchable = f"{raw.title} {raw.description} {' '.join(raw.skills)}".casefold()
    return not request.keywords or any(keyword.casefold() in searchable for keyword in request.keywords)


def _as_raw_job(job: JobListing) -> RawJob:
    return RawJob(
        company=job.company, title=job.title, location=job.location,
        work_mode=job.work_mode, url=job.url, application_url=job.application_url,
        description=job.description, requirements=job.requirements,
        skills=tuple(job.skills), required_skills=tuple(job.required_skills),
        preferred_skills=tuple(job.preferred_skills), experience=job.experience,
        salary=job.salary, source=job.source, posted_date=job.posted_date,
    )


def search_jobs(session: Session, request: JobSearchRequest) -> JobSearchResponse:
    profile_record = session.get(CareerProfileRecord, 1)
    profile = profile_record.data if profile_record else {}
    target = profile.get("career_target") if isinstance(profile.get("career_target"), dict) else {}
    request = request.model_copy(update={
        "role": request.role or str(target.get("primary_role") or ""),
        "roles": (
            [request.role] if request.role else request.roles or
            [role for role in [target.get("primary_role"), *(target.get("secondary_roles") or [])] if role]
        ),
        "location_preferences": request.location_preferences or (
            [request.location] if request.location else list(target.get("preferred_locations") or [])
            + list(target.get("work_authorization_countries") or [])
        ),
        "remote_preference": request.remote_preference or str(target.get("work_mode") or ""),
        "experience_level": request.experience_level or str(target.get("experience_level") or ""),
    })
    if not request.roles and not request.keywords:
        return JobSearchResponse(
            status="WAITING_FOR_USER", query=request, total_found=0,
            duplicates_removed=0, existing_listings_updated=0, jobs=[],
            sources=[SourceReport(
                source="job_search", status="waiting_for_user",
                error="Set a primary or secondary target role in Career Profile, or enter a role/keyword to search.",
            )],
        )
    names = configured_sources()
    if not names:
        return JobSearchResponse(
            status="NEEDS_CONFIGURATION", query=request, total_found=0,
            duplicates_removed=0, existing_listings_updated=0, jobs=[],
            sources=[SourceReport(source="job_search", status="unavailable", error="Configure JOB_SEARCH_SOURCES with arbeitnow and/or remoteok.")],
        )

    with ThreadPoolExecutor(max_workers=len(names)) as executor:
        futures = {name: executor.submit(SOURCES[name]) for name in names}
        raw_by_source: dict[str, list[RawJob]] = {}
        reports: list[SourceReport] = []
        for name, future in futures.items():
            try:
                listings = future.result()
                raw_by_source[name] = listings
                reports.append(SourceReport(source=name, status="success", jobs_found=len(listings)))
            except (URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as error:
                reports.append(SourceReport(source=name, status="unavailable", error=f"{type(error).__name__}: {error}"))

    latest_resume = session.scalar(select(MasterResumeVersion).order_by(MasterResumeVersion.created_at.desc()).limit(1))
    resume_text = latest_resume.content if latest_resume else ""
    for saved in session.scalars(select(JobListing)):
        saved.match_score, saved.match_breakdown = _score(_as_raw_job(saved), request, profile, resume_text)
    all_raw = [job for listings in raw_by_source.values() for job in listings]
    unique: dict[str, RawJob] = {}
    for item in all_raw:
        canonical = _canonical_url(item.url or item.application_url)
        if canonical and canonical not in unique:
            unique[canonical] = item
    duplicates_removed = len(all_raw) - len(unique)

    stored: list[JobListing] = []
    existing_listings_updated = 0
    for key, raw in unique.items():
        if not raw.title or not raw.url or not _matches_filters(raw, request):
            continue
        score, breakdown = _score(raw, request, profile, resume_text)
        existing = session.scalar(select(JobListing).where(JobListing.canonical_url == key))
        if existing is None:
            existing = JobListing(canonical_url=key)
            session.add(existing)
        else:
            existing_listings_updated += 1
        existing.company = raw.company
        existing.title = raw.title
        existing.location = raw.location
        existing.work_mode = raw.work_mode
        existing.url = raw.url
        existing.application_url = raw.application_url or raw.url
        existing.description = raw.description
        existing.requirements = raw.requirements
        existing.skills = list(raw.skills)
        existing.required_skills = _skills(raw.requirements)[0]
        existing.preferred_skills = _skills(raw.requirements)[1]
        existing.experience = raw.experience
        existing.salary = raw.salary
        existing.source = raw.source
        existing.posted_date = raw.posted_date
        existing.match_score = score
        existing.match_breakdown = breakdown
        existing.updated_at = datetime.now(timezone.utc)
        stored.append(existing)
    session.commit()
    stored = [job for job in stored if job.match_score >= request.minimum_match_score]
    stored.sort(key=lambda item: (item.match_score, item.posted_date), reverse=True)
    result_jobs = [JobResponse(
        id=str(job.id), company=job.company, title=job.title, location=job.location,
        work_mode=job.work_mode, url=job.url, application_url=job.application_url,
        description=job.description, requirements=job.requirements, skills=job.skills,
        required_skills=job.required_skills, preferred_skills=job.preferred_skills,
        experience=job.experience, salary=job.salary, source=job.source,
        posted_date=job.posted_date, match_score=job.match_score,
        date_found=job.created_at.date().isoformat(), match_breakdown=job.match_breakdown,
    ) for job in stored[:request.limit]]
    successful_sources = sum(1 for report in reports if report.status == "success")
    failed_sources = len(reports) - successful_sources
    status = "SUCCESS" if successful_sources and not failed_sources else (
        "PARTIAL_SUCCESS" if successful_sources else "FAILED"
    )
    return JobSearchResponse(
        status=status, query=request, total_found=len(result_jobs),
        duplicates_removed=duplicates_removed,
        existing_listings_updated=existing_listings_updated,
        jobs=result_jobs, sources=reports,
    )


def get_saved_jobs(
    session: Session,
    minimum_match_score: int = 0,
    limit: int = 100,
    role: str = "",
    location: str = "",
) -> list[JobResponse]:
    profile_record = session.get(CareerProfileRecord, 1)
    profile = profile_record.data if profile_record else {}
    target = profile.get("career_target") if isinstance(profile.get("career_target"), dict) else {}
    target_roles = [role] if role else [
        item for item in [target.get("primary_role"), *(target.get("secondary_roles") or [])] if item
    ]
    request = JobSearchRequest(
        role=role or (target_roles[0] if target_roles else ""),
        roles=target_roles,
        location=location or ", ".join(target.get("preferred_locations") or []),
        location_preferences=[location] if location else list(target.get("preferred_locations") or [])
        + list(target.get("work_authorization_countries") or []),
        remote_preference=str(target.get("work_mode") or ""),
        experience_level=str(target.get("experience_level") or ""),
        minimum_match_score=minimum_match_score,
    )
    resume = session.scalar(select(MasterResumeVersion).order_by(MasterResumeVersion.created_at.desc()).limit(1))
    resume_text = resume.content if resume else ""
    candidates = list(session.scalars(
        select(JobListing)
    ))
    records = []
    for item in candidates:
        raw = _as_raw_job(item)
        if target_roles and not _matches_filters(raw, request):
            continue
        item.match_score, item.match_breakdown = _score(raw, request, profile, resume_text)
        if item.match_score >= minimum_match_score:
            records.append(item)
    records.sort(key=lambda item: (item.match_score, item.created_at), reverse=True)
    session.commit()
    records = records[:limit]
    return [_job_response(record) for record in records]


def _job_response(job: JobListing) -> JobResponse:
    return JobResponse(
        id=str(job.id), company=job.company, title=job.title, location=job.location,
        work_mode=job.work_mode, url=job.url, application_url=job.application_url,
        description=job.description, requirements=job.requirements, skills=job.skills,
        required_skills=job.required_skills, preferred_skills=job.preferred_skills,
        experience=job.experience, salary=job.salary, source=job.source,
        posted_date=job.posted_date, date_found=job.created_at.date().isoformat(),
        match_score=job.match_score, match_breakdown=job.match_breakdown,
    )
