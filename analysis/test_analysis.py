import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("prep", Path(__file__).with_name("02_prepare.py"))
prep = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prep)

assert prep.parse_vj_salary("8.5 - 10.0 triệu") == (8.5, 10.0)
assert all(x != x for x in prep.parse_vj_salary("0.0 triệu"))  # NaN = negotiable
assert prep.parse_experience("6 tháng") == 0.5 and prep.parse_experience("Không yêu cầu") == 0
assert prep.locations("hà đông, quận 7") == (["Hà Nội", "Hồ Chí Minh"], ["Hà Nội", "Hồ Chí Minh"])
assert prep.locations("Đà Nẵng: Phường Hòa Xuân, Khánh Hòa")[0] == ["Đà Nẵng"]
assert prep.locations("Phường Sài Gòn (Phường Sài Gòn thuộc Quận 1 cũ)")[0] == ["Hồ Chí Minh"]
assert prep.locations("khánh hoà; biên hoà")[0] == ["Khánh Hòa", "Đồng Nai"]
print("ok")
