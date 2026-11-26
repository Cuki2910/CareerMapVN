"""Smoke test: the dashboard renders with default, narrowed and province filters, without exceptions."""
from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).with_name("app.py"))

at = AppTest.from_file(APP, default_timeout=120).run()
assert not at.exception, at.exception
assert at.metric[0].value != "0"


def check(step):
    at.run()
    assert not at.exception, (step, at.exception)


province = at.sidebar.selectbox[0]
province.set_value("Đà Nẵng"); check("province")                         # same path as a map click
assert "Đà Nẵng" in at.metric[0].label
province.set_value("Lai Châu"); check("tiny province")                   # 0 postings -> info, no crash
province.set_value("All of Vietnam"); check("reset")

at.sidebar.multiselect[0].set_value(["Data role"]); check("tier")
for metric in ["Number of postings", "Share requiring a skill", "Median advertised salary"]:
    at.selectbox[0].set_value(metric); check(metric)                     # map colour metric

at.sidebar.multiselect[3].set_value(["Qlik", "PyTorch", "SAS"]); check("empty")  # empty -> warning
assert at.warning, "expected an empty-filter warning"
print("dashboard ok")
