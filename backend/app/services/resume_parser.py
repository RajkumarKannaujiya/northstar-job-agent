import re
from datetime import datetime

from docx import Document
from pypdf import PdfReader


KNOWN_SKILLS = {
    "python", "java", "javascript", "typescript", "sql", "excel", "power bi", "tableau",
    "react", "node.js", "fastapi", "django", "aws", "azure", "gcp", "html", "css",
    "shopify", "seo", "sem", "google analytics", "project management", "communication",
    "leadership", "salesforce", "figma", "docker", "kubernetes", "git", "pandas",
}


def extract_text(filename: str, content: bytes) -> str:
    suffix = filename.lower().rsplit(".", 1)[-1]
    if suffix == "txt":
        return content.decode("utf-8", errors="replace")
    if suffix == "pdf":
        import io
        reader = PdfReader(io.BytesIO(content))
        pages = []
        for page in reader.pages:
            try:
                page_text = page.extract_text(extraction_mode="layout")
            except TypeError:
                page_text = page.extract_text()
            pages.append(page_text or "")
        return "\n".join(pages)
    if suffix == "docx":
        import io
        document = Document(io.BytesIO(content))
        return "\n".join(paragraph.text for paragraph in document.paragraphs)
    raise ValueError("Only PDF, DOCX, and TXT resumes are supported")


def parse_resume(text: str) -> dict:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    email = _first(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", text, re.I)
    phone = _first(r"(?<!\w)(?:\+?\d[\d\s().-]{7,}\d)(?!\w)", text)
    # Name extraction is intentionally conservative; ambiguous names remain blank for user review.
    name = lines[0][:120] if lines and len(lines[0].split()) <= 5 and not re.search(r"@|resume|curriculum", lines[0], re.I) else ""
    lower = text.lower()
    skills = sorted(skill for skill in KNOWN_SKILLS if re.search(rf"(?<![\w+#.]){re.escape(skill)}(?![\w+#.])", lower))
    soft_skills = [skill for skill in skills if skill in {"communication", "leadership", "project management"}]
    technical_skills = [skill for skill in skills if skill not in soft_skills]
    headings = {"experience", "work experience", "employment", "professional experience"}
    experiences = []
    for idx, line in enumerate(lines):
        if line.lower().strip(":") in headings:
            for entry in lines[idx + 1:idx + 7]:
                if entry.lower().strip(":") in {"education", "skills", "projects", "certifications"}:
                    break
                if len(entry) > 3:
                    experiences.append({"text": entry, "evidence": "explicit"})
            break
    edu_head = next((i for i, line in enumerate(lines) if line.lower().strip(":") in {"education", "academic background"}), None)
    education = []
    if edu_head is not None:
        for entry in lines[edu_head + 1:edu_head + 5]:
            if entry.lower().strip(":") in {"experience", "skills", "projects", "certifications"}:
                break
            education.append({"text": entry, "evidence": "explicit"})
    certifications = []
    cert_head = next((i for i, line in enumerate(lines) if "certification" in line.lower()), None)
    if cert_head is not None:
        certifications = [line for line in lines[cert_head + 1:cert_head + 7] if len(line) > 2]
    projects = []
    proj_head = next((i for i, line in enumerate(lines) if line.lower().strip(":") in {"projects", "selected projects"}), None)
    if proj_head is not None:
        projects = [line for line in lines[proj_head + 1:proj_head + 7] if len(line) > 2]
    years = _estimate_years(text)
    education_text = " ".join(item.get("text", "") for item in education)
    degree = next((item.get("text", "") for item in education if re.search(r"\b(bachelor|master|ph\.?d|b\.?tech|m\.?tech|b\.?sc|m\.?sc|mba|bca|mca|diploma)\b", item.get("text", ""), re.I)), "")
    graduation = _first(r"\b(?:19|20)\d{2}\b", education_text)
    location = next((line for line in lines[:5] if re.search(r"\b(India|Gujarat|Maharashtra|Delhi|Surat|Ahmedabad|Mumbai|Vadodara)\b", line, re.I)), "")
    return {
        "name": name, "email": email, "phone": phone, "location": location,
        "skills": skills, "technical_skills": technical_skills, "soft_skills": soft_skills,
        "explicit_skills": skills, "inferred_skills": [], "missing_skills": [],
        "experience": experiences, "education": education, "projects": projects,
        "degree": degree, "graduation_year": int(graduation) if graduation else None,
        "certifications": certifications, "job_titles": _extract_titles(experiences),
        "companies": _extract_companies(experiences), "years_of_experience": years, "salary_expectations": None,
        "notice_period": None, "employment_type": None,
        "parser_notes": ["Review extracted fields before using them in applications."],
    }


def _first(pattern: str, text: str, flags: int = 0) -> str:
    match = re.search(pattern, text, flags)
    return match.group(0).strip() if match else ""


def _estimate_years(text: str) -> float:
    # Conservative estimate based on explicit year ranges, capped to avoid implausible extraction.
    ranges = re.findall(r"\b(19\d{2}|20\d{2})\s*[-–to]+\s*(present|current|20\d{2})\b", text, re.I)
    intervals: list[tuple[int, int]] = []
    current = datetime.now().year
    for start, end in ranges:
        intervals.append((int(start), min(current, int(end) if end.isdigit() else current)))
    intervals.sort()
    merged: list[list[int]] = []
    for start, end in intervals:
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    total = sum(max(0, end - start) for start, end in merged)
    return float(min(total, 50))


def _extract_titles(experience: list[dict]) -> list[str]:
    titles = []
    for item in experience:
        first = re.split(r"\s+[|—–-]\s+|,| at ", item.get("text", ""), maxsplit=1, flags=re.I)[0].strip()
        if first and len(first) <= 100:
            titles.append(first)
    return titles


def _extract_companies(experience: list[dict]) -> list[str]:
    companies = []
    for item in experience:
        parts = [part.strip() for part in re.split(r"\s+[|—–-]\s+|,| at ", item.get("text", ""), flags=re.I)]
        if len(parts) >= 2 and parts[1] and len(parts[1]) <= 120:
            companies.append(parts[1])
    return companies
