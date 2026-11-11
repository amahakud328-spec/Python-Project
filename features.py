"""Small text-processing helpers kept independent from the Tkinter UI."""

from datetime import datetime


DOCUMENT_TEMPLATES = {
    "College assignment": (
        "ASSIGNMENT TITLE\n"
        "Subject: \n"
        "Name: \n"
        "Roll Number: \n"
        "Date: \n\n"
        "1. Introduction\n\n"
        "2. Objectives\n\n"
        "3. Main Content\n\n"
        "4. Conclusion\n\n"
        "References\n"
    ),
    "Seminar report": (
        "SEMINAR REPORT\n"
        "Topic: \n"
        "Presented by: \n"
        "Department: \n"
        "Date: \n\n"
        "Abstract\n\n"
        "Introduction\n\n"
        "Methodology\n\n"
        "Discussion\n\n"
        "Conclusion\n\n"
        "References\n"
    ),
    "Meeting notes": (
        "MEETING NOTES\n"
        "Date and time: \n"
        "Attendees: \n"
        "Agenda: \n\n"
        "Discussion\n\n"
        "Decisions\n\n"
        "Action items\n"
        "- [ ] Task — Owner — Due date\n"
    ),
    "Daily journal": (
        "DAILY JOURNAL\n"
        "Date: \n\n"
        "Today I am grateful for:\n\n"
        "What I learned:\n\n"
        "Highlights:\n\n"
        "Tomorrow I will:\n"
    ),
    "Project documentation": (
        "PROJECT DOCUMENTATION\n"
        "Project name: \n"
        "Team: \n"
        "Version: \n\n"
        "Overview\n\n"
        "Requirements\n\n"
        "Architecture\n\n"
        "Implementation\n\n"
        "Testing\n\n"
        "Future work\n"
    ),
    "Study notes": (
        "STUDY NOTES\n"
        "Subject: \n"
        "Unit / Topic: \n"
        "Date: \n\n"
        "Key concepts\n\n"
        "Definitions\n\n"
        "Examples\n\n"
        "Questions to review\n"
    ),
}


def count_text(text: str) -> dict[str, int]:
    """Return word, character, and displayed-line counts for text."""
    return {
        "words": len(text.split()),
        "characters": len(text),
        "lines": text.count("\n") + 1,
    }


def convert_case(text: str, mode: str) -> str:
    """Convert text using one of SmartPad's supported case modes."""
    conversions = {
        "upper": str.upper,
        "lower": str.lower,
        "title": str.title,
    }
    try:
        converter = conversions[mode]
    except KeyError as error:
        raise ValueError(f"Unsupported case mode: {mode}") from error
    return converter(text)


def current_datetime() -> str:
    """Return the current local date and time in a readable format."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
