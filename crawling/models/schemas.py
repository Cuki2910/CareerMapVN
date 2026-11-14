from datetime import date
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator
from typing import Optional, List


class JobAdSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)

    # Basic Information
    job_title: str = Field(..., min_length=1, description="The title of the job position")
    company_name: Optional[str] = Field(default=None, description="The company offering the job")
    job_category: Optional[str] = Field(default=None, description="The general category or industry of the job")
    sub_category: Optional[str] = Field(default=None, description="The more specific sub-category within the job category")
    industry: Optional[str] = Field(default=None, description="The industry or sector of the job")
    category: Optional[str] = Field(default=None, description="Dataset category supplied by the operator, never inferred from an unknown taxonomy")

    # Location
    location: Optional[str] = Field(default=None, description="The specific location of the job (e.g., city, province, or region)")
    country: Optional[str] = Field(default=None, description="The country where the job is based")

    # Posting details
    posting_date: Optional[str] = Field(default=None, description="The date when the job was posted")
    deadline: Optional[str] = Field(default=None, description="The application deadline, if available")
    url: HttpUrl = Field(..., description="The URL of the job advertisement")

    # Job Requirements
    qualifications: Optional[List[str]] = Field(default=None, description="Required qualifications such as degree, major, certifications")
    technical_skills: Optional[List[str]] = Field(default=None, description="Required technical skills (e.g., programming languages, tools)")
    soft_skills: Optional[List[str]] = Field(default=None, description="Required soft skills (e.g., communication, teamwork)")
    languages_required: Optional[List[str]] = Field(default=None, description="Languages required (e.g., Vietnamese, English)")
    experience_required: Optional[float] = Field(default=None, ge=0, allow_inf_nan=False, description="Number of years of experience required")

    # Job Conditions
    salary: Optional[str] = Field(default=None, description="The salary or compensation details (e.g., range, negotiable)")
    salary_min: Optional[float] = Field(default=None, ge=0, allow_inf_nan=False, description="Monthly lower bound in millions of VND; null if unknown")
    salary_max: Optional[float] = Field(default=None, ge=0, allow_inf_nan=False, description="Monthly upper bound in millions of VND; null if unknown")
    salary_avg: Optional[str] = Field(default=None, description="Exact midpoint as 'X triệu' only for a known bounded monthly VND salary")
    contract_type: Optional[str] = Field(default=None, description="Type of contract (full-time, part-time, internship, freelance)")
    working_hours: Optional[str] = Field(default=None, description="Working hours (e.g., 9-5, shift-based)")
    benefits: Optional[List[str]] = Field(default=None, description="Benefits offered (insurance, bonuses, training, etc.)")

    # Textual Information (for NLP tasks)
    description: str = Field(..., min_length=1, description="Full job description, including responsibilities")
    requirements_text: Optional[str] = Field(default=None, description="Unstructured requirements section text, for NLP parsing")

    @field_validator("posting_date", "deadline")
    @classmethod
    def validate_date(cls, value):
        if value is not None and date.fromisoformat(value).isoformat() != value:
            raise ValueError("Dates must use YYYY-MM-DD")
        return value

    @model_validator(mode="after")
    def validate_salary(self):
        from .source_fields import salary_fields

        if self.posting_date and self.deadline and self.deadline < self.posting_date:
            raise ValueError("Deadline must not precede posting date")
        expected = salary_fields(self.salary)
        if any(getattr(self, field) != value for field, value in expected.items()):
            raise ValueError("Salary bounds and average must be derived from the raw salary without guessing")
        return self
