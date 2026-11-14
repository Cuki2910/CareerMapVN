import re
import unicodedata
from datetime import datetime
from decimal import Decimal
from urllib.parse import urlsplit


def plain_text(text):
    text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = text.replace("**", "").replace("__", "")
    text = re.sub(r"(?m)^\s*(?:#{1,6}\s+|_+)|_+\s*$", "", text)
    return "\n".join(line.strip() for line in text.splitlines() if line.strip())


def folded(text):
    text = unicodedata.normalize("NFD", text.lower().replace("đ", "d"))
    return "".join(character for character in text if not unicodedata.combining(character) and not character.isspace())


def job_markdown(markdown, url):
    if urlsplit(url).hostname not in {"topcv.vn", "www.topcv.vn"}:
        return markdown
    title = re.search(r"^#[ \t]+.+$", markdown, re.MULTILINE)
    if not title:
        return markdown
    footer = re.search(r"^Danh mục Nghề liên quan\s*$", markdown[title.start():], re.MULTILINE)
    end = title.start() + footer.start() if footer else len(markdown)
    return markdown[title.start():end]


def source_sections(markdown):
    aliases = {
        "motacongviec": "description", "jobdescription": "description",
        "yeucauungvien": "requirements_text", "yeucaucongviec": "requirements_text",
        "jobrequirements": "requirements_text", "requirements": "requirements_text",
        "candidaterequirements": "requirements_text",
        "quyenloi": "benefits", "quyenloiungvien": "benefits", "benefits": "benefits",
        "thoigianlamviec": "working_hours", "workinghours": "working_hours",
        "workschedule": "working_hours",
    }
    headings = list(re.finditer(r"^(#{1,6})[ \t]+(.+?)\s*$", markdown, re.MULTILINE))
    sections = {}
    levels = {}
    for index, heading in enumerate(headings):
        name = folded(heading.group(2).strip(" :"))
        field = aliases.get(name)
        if not field:
            continue
        end = next((later.start() for later in headings[index + 1:] if len(later.group(1)) <= len(heading.group(1))), len(markdown))
        text = plain_text(markdown[heading.end():end])
        if text and (field not in sections or len(heading.group(1)) < levels[field]):
            sections[field] = text
            levels[field] = len(heading.group(1))
    return sections


def salary_fields(salary):
    empty = {"salary_min": None, "salary_max": None, "salary_avg": None}
    if not salary:
        return empty
    text = unicodedata.normalize("NFD", salary.lower().replace("đ", "d"))
    text = "".join(character for character in text if not unicodedata.combining(character))
    text = text.replace("–", "-").replace("—", "-")
    number = r"(?:\d{1,3}(?:[.,]\d{3})+|\d+(?:[.,]\d{1,2})?)"
    unit = r"(?:trieu(?:\s+(?:dong|vnd))?|tr|vnd|dong)"
    match = re.fullmatch(
        rf"\s*(?P<prefix>tu|from|tren|hon|up to|toi da|duoi|den)?\s*"
        rf"(?P<first>{number})\s*(?P<unit1>{unit})?"
        rf"(?:\s*(?:-|den|to)\s*(?P<second>{number})\s*(?P<unit2>{unit})?)?"
        r"\s*(?:gross|net)?\s*(?:(?:/|moi)\s*(?:thang|month))?\s*", text,
    )
    if not match or not (match["unit1"] or match["unit2"]):
        return empty

    def amount(raw, currency):
        if re.fullmatch(r"\d{1,3}(?:[.,]\d{3})+", raw):
            raw = raw.replace(".", "").replace(",", "")
        value = Decimal(raw.replace(",", "."))
        return value if currency.startswith(("trieu", "tr")) else value / Decimal(1000000)

    first = amount(match["first"], match["unit1"] or match["unit2"])
    if match["second"]:
        if match["prefix"] not in (None, "tu", "from"):
            return empty
        second = amount(match["second"], match["unit2"] or match["unit1"])
        if first > second:
            return empty
        average = format(((first + second) / 2).normalize(), "f")
        return {"salary_min": float(first), "salary_max": float(second), "salary_avg": average + " triệu"}
    if match["prefix"] in ("up to", "toi da", "duoi", "den"):
        return {**empty, "salary_max": float(first)}
    if match["prefix"] in ("tu", "from", "tren", "hon"):
        return {**empty, "salary_min": float(first)}
    return {"salary_min": float(first), "salary_max": float(first), "salary_avg": format(first.normalize(), "f") + " triệu"}


def normalize_job(data, markdown, category=None):
    markdown = job_markdown(markdown, data.get("url", ""))
    sections = source_sections(markdown)
    if not sections.get("description"):
        raise ValueError("No recognizable job-description section; refusing unverified extraction")
    data["description"] = sections["description"]
    for field in ("requirements_text", "working_hours"):
        data[field] = sections.get(field)
    if urlsplit(data.get("url", "")).hostname in {"topcv.vn", "www.topcv.vn"}:
        title = re.search(r"^#[ \t]+(.+)$", markdown, re.MULTILINE)
        if title:
            data["job_title"] = plain_text(title.group(1))
    qualifications = [
        line.lstrip("•-* ") for line in (sections.get("requirements_text") or "").splitlines()
        if re.search(
            r"\b(?:tốt nghiệp|chứng chỉ)\b|^[•*\-\s]*(?:ưu tiên\s+)?(?:các\s+)?chuyên ngành\b",
            unicodedata.normalize("NFC", line), re.IGNORECASE,
        )
    ]
    if qualifications:
        data["qualifications"] = qualifications + [
            value for value in data.get("qualifications") or []
            if folded(value).rstrip(".") not in folded("\n".join(qualifications))
            and folded(value).rstrip(".") in folded(plain_text(markdown))
        ]
    benefits = sections.get("benefits")
    data["benefits"] = [
        line.lstrip("•-* ") for line in benefits.splitlines()
        if folded(line) not in {"phucloi", "hotro", "quyenloibosung"}
    ] if benefits else None
    if benefits:
        income = re.search(r"(?im)^\s*[•*\-]?\s*Thu nhập\s*:\s*(.+)$", benefits)
        if income:
            data["salary"] = income.group(1).strip()
    if data.get("salary"):
        if not isinstance(data["salary"], str):
            raise ValueError("Salary must be source text, not a guessed number")
        salary_text = folded(plain_text(data["salary"])).replace("–", "-").replace("—", "-")
        source_text = folded(plain_text(markdown)).replace("–", "-").replace("—", "-")
        if salary_text not in source_text:
            raise ValueError("Salary wording is not present in the source")
    data["category"] = category
    data.update(salary_fields(data.get("salary")))
    for field in ("posting_date", "deadline"):
        if data.get(field):
            for pattern in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
                try:
                    data[field] = datetime.strptime(data[field], pattern).date().isoformat()
                    break
                except ValueError:
                    continue
            else:
                raise ValueError(f"Invalid {field}: {data[field]}")
    if data.get("country") and folded(data["country"]) == "vietnam":
        data["country"] = "Việt Nam"
    contracts = {"full-time": "Toàn thời gian", "part-time": "Bán thời gian", "internship": "Thực tập", "freelance": "Freelance"}
    if isinstance(data.get("contract_type"), str):
        data["contract_type"] = contracts.get(data["contract_type"].lower(), data["contract_type"])
    return data
