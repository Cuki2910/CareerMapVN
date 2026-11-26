"""Smoke test: the dashboard renders with default and narrowed filters, without exceptions."""
from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).with_name("app.py"))

at = AppTest.from_file(APP, default_timeout=120).run()
assert not at.exception, at.exception
assert at.metric[0].value != "0"

at.sidebar.multiselect[0].set_value(["Data role"]).run()          # data roles only
assert not at.exception, at.exception
at.sidebar.multiselect[2].set_value(["Hồ Chí Minh"]).run()        # one region
assert not at.exception, at.exception
at.sidebar.multiselect[5].set_value(["SQL", "Python"]).run()      # must-have skills
assert not at.exception, at.exception

at.sidebar.multiselect[5].set_value(["Qlik", "PyTorch", "SAS"]).run()  # empty result -> warning, no crash
assert not at.exception, at.exception
assert at.warning, "expected an empty-filter warning"
print("dashboard ok")
