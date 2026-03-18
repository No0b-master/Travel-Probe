from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


class ATSCheckRequest(BaseModel):
    resume_text: str = Field(..., min_length=50, description="Raw resume text")
    job_description: str = Field(..., min_length=50, description="Target job description")
    target_role: Optional[str] = Field(default=None, description="Optional target role")
    industry: Optional[str] = Field(default=None, description="Optional target industry")
    resume_id: Optional[int] = Field(default=None, ge=1, description="Optional stored resume id")
    resume_file_name: Optional[str] = Field(default=None, max_length=255, description="Optional stored resume file name")
    resume_file_type: Optional[str] = Field(default=None, max_length=16, description="Optional stored resume file type")


class ScoreBreakdown(BaseModel):
    keyword_match: float
    section_completeness: float
    readability: float
    uae_market_fit: float


class ATSCheckResponse(BaseModel):
    overall_score: float
    breakdown: ScoreBreakdown
    missing_keywords: List[str]
    matched_keywords: List[str]
    section_gaps: List[str]
    recommendations: List[str]


class ATSUsageResponse(BaseModel):
    daily_limit: int
    used_today: int
    remaining_today: int
    reset_at_utc: datetime


class ATSScanHistoryItem(BaseModel):
    scan_id: int
    resume_id: Optional[int] = None
    resume_file_name: Optional[str] = None
    resume_file_type: Optional[str] = None
    target_role: Optional[str] = None
    industry: Optional[str] = None
    resume_text_snapshot: str
    job_description_snapshot: str
    overall_score: float
    breakdown: ScoreBreakdown
    matched_keywords: List[str]
    missing_keywords: List[str]
    section_gaps: List[str]
    recommendations: List[str]
    matched_keywords_count: int
    missing_keywords_count: int
    section_gaps_count: int
    summary: str
    created_at: datetime


class ResumeOptimizeRequest(BaseModel):
    resume_text: str = Field(..., min_length=50)
    job_description: Optional[str] = Field(default=None)
    target_role: Optional[str] = Field(default=None)
    preferred_emirate: Optional[str] = Field(default=None)


class ResumeOptimizeResponse(BaseModel):
    optimized_summary: str
    rewritten_bullets: List[str]
    skills_to_add: List[str]
    uae_localization_tips: List[str]


class KeywordGapRequest(BaseModel):
    resume_text: str = Field(..., min_length=50)
    job_description: str = Field(..., min_length=50)


class KeywordGapResponse(BaseModel):
    missing_keywords: List[str]
    high_priority_keywords: List[str]
    coverage_percentage: float


class ResumeExtractResponse(BaseModel):
    file_name: str
    file_type: str
    extracted_text: str
    character_count: int


class RegisterRequest(BaseModel):
    full_name: str = Field(..., min_length=2, max_length=100)
    email: str = Field(..., min_length=5, max_length=255)
    password: str = Field(..., min_length=8, max_length=128)


class LoginRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=255)
    password: str = Field(..., min_length=8, max_length=128)


class GoogleAuthRequest(BaseModel):
    id_token: str = Field(..., min_length=20)


class AuthResponse(BaseModel):
    user_id: int
    full_name: str
    email: str
    access_token: str
    token_type: str = "Bearer"


class RegisteredUser(BaseModel):
    user_id: int
    full_name: str
    email: str
    profile_image_url: Optional[str] = None


class CandidateProfileUpdateRequest(BaseModel):
    full_name: str = Field(..., min_length=2, max_length=100)
    dob: Optional[date] = None
    current_organization: Optional[str] = Field(default=None, max_length=255)
    current_role: Optional[str] = Field(default=None, max_length=255)
    experience_years: Optional[float] = Field(default=None, ge=0, le=60)
    linkedin_url: Optional[str] = Field(default=None, max_length=1024)
    github_url: Optional[str] = Field(default=None, max_length=1024)
    twitter_url: Optional[str] = Field(default=None, max_length=1024)

    @field_validator("experience_years")
    @classmethod
    def validate_experience_years_precision(cls, value: Optional[float]) -> Optional[float]:
        if value is None:
            return value

        rounded = round(value, 1)
        if abs(value - rounded) > 1e-9:
            raise ValueError("experience_years must have at most one decimal place")
        return rounded

    @field_validator("linkedin_url", "github_url", "twitter_url")
    @classmethod
    def validate_social_url(cls, value: Optional[str], info):
        if value is None:
            return value

        normalized = value.strip()
        if not normalized:
            return None

        if not (normalized.startswith("http://") or normalized.startswith("https://")):
            raise ValueError(f"{info.field_name} must start with http:// or https://")

        expected_domains = {
            "linkedin_url": "linkedin.com",
            "github_url": "github.com",
            "twitter_url": ("x.com", "twitter.com"),
        }
        expected = expected_domains[info.field_name]
        value_lower = normalized.lower()

        if isinstance(expected, tuple):
            if not any(domain in value_lower for domain in expected):
                raise ValueError(f"{info.field_name} must be a valid {', '.join(expected)} URL")
        else:
            if expected not in value_lower:
                raise ValueError(f"{info.field_name} must be a valid {expected} URL")

        return normalized


class CandidateProfileResponse(BaseModel):
    user_id: int
    full_name: str
    email: str
    profile_image_url: Optional[str] = None
    dob: Optional[date] = None
    current_organization: Optional[str] = None
    current_role: Optional[str] = None
    experience_years: Optional[float] = None
    linkedin_url: Optional[str] = None
    github_url: Optional[str] = None
    twitter_url: Optional[str] = None


class StoredResumeSummary(BaseModel):
    resume_id: int
    file_name: str
    file_type: str
    character_count: int
    created_at: datetime


class StoredResumeDetail(StoredResumeSummary):
    extracted_text: str
    storage_provider: str
    file_url: Optional[str] = None
