import csv
import json
from pathlib import Path
from tempfile import NamedTemporaryFile


ROOT = Path(__file__).resolve().parents[1]


def csv_value(field, value):
    if value is None:
        return ""
    if field == "experience_required":
        return "Không yêu cầu" if value == 0 else f"{value:g} năm"
    if isinstance(value, (int, float)):
        return f"{value:g}"
    return str(value)


def export_csv(jobs_dir, output):
    with (ROOT / "data/VietJobs_sample.csv").open(encoding="utf-8", newline="") as sample:
        fields = next(csv.reader(sample))

    paths = sorted(jobs_dir.glob("*.json"))
    rows = []
    for path in paths:
        if path.name.startswith("._"):
            continue
        record = json.loads(path.read_text(encoding="utf-8"))
        rows.append([csv_value(field, record.get(field)) for field in fields])
    if not rows:
        raise ValueError("No job records found; existing CSV left untouched")

    temporary_path = None
    try:
        with NamedTemporaryFile(mode="w", encoding="utf-8", newline="", dir=output.parent, delete=False) as temporary:
            temporary_path = Path(temporary.name)
            csv.writer(temporary).writerows([fields, *rows])
        with temporary_path.open(encoding="utf-8", newline="") as saved:
            assert list(csv.reader(saved)) == [fields, *rows], "CSV round-trip failed"
        temporary_path.replace(output)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    return len(rows)


def main():
    output = ROOT / "data/CareerMapVN_jobs.csv"
    count = export_csv(ROOT / "data/continuous/jobs", output)
    print(f"{output}: {count} jobs")


if __name__ == "__main__":
    main()
