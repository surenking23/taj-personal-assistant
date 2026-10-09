import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Specialist:
    name: str
    keywords: tuple[str, ...]
    steps: tuple[str, ...]

    def matches(self, goal: str) -> bool:
        return any(re.search(rf"\b{re.escape(keyword)}\b", goal, re.IGNORECASE) for keyword in self.keywords)


SPECIALISTS = (
    Specialist(
        "Job Search Agent",
        ("job", "jobs", "career", "resume", "application", "interview"),
        ("Clarify role, location, and constraints.", "Gather and verify career information.", "Prepare a ranked, source-backed result."),
    ),
    Specialist(
        "Data Analyst Agent",
        ("data", "dataset", "csv", "excel", "sql", "chart", "analyze"),
        ("Inspect the supplied data and its schema.", "Validate assumptions and calculate requested measures.", "Summarize findings and limitations."),
    ),
    Specialist(
        "Research Agent",
        ("research", "compare", "sources", "find", "look up"),
        ("Identify reliable sources relevant to the goal.", "Cross-check material claims.", "Report findings with source links and uncertainty."),
    ),
    Specialist(
        "Coding Agent",
        ("code", "coding", "bug", "debug", "refactor", "test", "build"),
        ("Inspect the relevant project and reproduce the requested behavior.", "Make a focused change using existing project conventions.", "Run targeted checks and report their results."),
    ),
    Specialist(
        "Personal Agent",
        ("task", "reminder", "calendar", "schedule", "week", "plan"),
        ("Identify priorities and any timing constraints.", "Prepare a task or schedule proposal.", "Confirm any external calendar changes before execution."),
    ),
)


def select_specialist(goal: str) -> Specialist:
    for specialist in SPECIALISTS:
        if specialist.matches(goal):
            return specialist
    return Specialist(
        "Orchestrator Agent",
        (),
        ("Break the goal into verifiable steps.", "Identify required information and safe tools.", "Report results and unresolved dependencies."),
    )
