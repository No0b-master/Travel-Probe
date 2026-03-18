import re
from collections import Counter
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from io import BytesIO
import json
import os
from typing import Any, List, Set, Tuple

from docx import Document
from fastapi import UploadFile
import mysql.connector
from mysql.connector.abstracts import MySQLConnectionAbstract
from pypdf import PdfReader
import requests

from app.models.schemas import (
    ATSCheckRequest,
    ATSCheckResponse,
    ATSScanHistoryItem,
    KeywordGapRequest,
    KeywordGapResponse,
    ResumeExtractResponse,
    ResumeOptimizeRequest,
    ResumeOptimizeResponse,
    ScoreBreakdown,
)


class ATSService:
    DAILY_SCAN_LIMIT = 10
    DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"

    REQUIRED_SECTIONS = [
        "summary",
        "experience",
        "skills",
        "education",
    ]

    UAE_KEYWORDS = {
        "uae",
        "gcc",
        "dubai",
        "abu dhabi",
        "emirates",
        "labour law",
        "free zone",
        "visa",
        "residency",
        "mohre",
        "vat",
        "esr",
    }

    STOPWORDS = {
        "the",
        "a",
        "an",
        "to",
        "and",
        "or",
        "of",
        "in",
        "for",
        "on",
        "with",
        "is",
        "are",
        "as",
        "by",
        "be",
        "this",
        "that",
        "from",
        "at",
        "you",
        "your",
        "our",
        "we",
        "will",
        "can",
    }

    SUPPORTED_FILE_TYPES = {"pdf", "docx"}

    def __init__(self) -> None:
        self.db_config = self._resolve_db_config()
        self.gemini_api_key = os.getenv("GEMINI_API_KEY", "").strip()
        self.gemini_model = os.getenv("GEMINI_MODEL", self.DEFAULT_GEMINI_MODEL).strip() or self.DEFAULT_GEMINI_MODEL

    def check_ats(self, payload: ATSCheckRequest, user_id: int) -> ATSCheckResponse:
        self._consume_scan_quota(user_id)
        result = self._check_ats_with_gemini(payload)
        self._save_scan_history(user_id, payload, result)
        return result

    def list_scan_history(self, user_id: int) -> list[ATSScanHistoryItem]:
        with closing(self._get_connection()) as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT
                    id AS scan_id,
                    resume_id,
                    resume_file_name,
                    resume_file_type,
                    target_role,
                    industry,
                    resume_text_snapshot,
                    job_description_snapshot,
                    overall_score,
                    breakdown_json,
                    matched_keywords_json,
                    missing_keywords_json,
                    section_gaps_json,
                    recommendations_json,
                    matched_keywords_count,
                    missing_keywords_count,
                    section_gaps_count,
                    summary,
                    created_at
                FROM ats_scan_history
                WHERE user_id = %s
                ORDER BY created_at DESC
                """,
                (user_id,),
            )
            rows = cursor.fetchall()

        history: list[ATSScanHistoryItem] = []
        for row in rows:
            history.append(
                ATSScanHistoryItem(
                    scan_id=row["scan_id"],
                    resume_id=row.get("resume_id"),
                    resume_file_name=row.get("resume_file_name"),
                    resume_file_type=row.get("resume_file_type"),
                    target_role=row.get("target_role"),
                    industry=row.get("industry"),
                    resume_text_snapshot=self._coerce_long_text(row.get("resume_text_snapshot")),
                    job_description_snapshot=self._coerce_long_text(row.get("job_description_snapshot")),
                    overall_score=float(row.get("overall_score") or 0),
                    breakdown=ScoreBreakdown(**self._parse_json_object(row.get("breakdown_json"))),
                    matched_keywords=self._parse_json_string_list(row.get("matched_keywords_json")),
                    missing_keywords=self._parse_json_string_list(row.get("missing_keywords_json")),
                    section_gaps=self._parse_json_string_list(row.get("section_gaps_json")),
                    recommendations=self._parse_json_string_list(row.get("recommendations_json")),
                    matched_keywords_count=int(row.get("matched_keywords_count") or 0),
                    missing_keywords_count=int(row.get("missing_keywords_count") or 0),
                    section_gaps_count=int(row.get("section_gaps_count") or 0),
                    summary=row.get("summary") or "",
                    created_at=row["created_at"],
                )
            )

        return history

    def delete_scan_history_item(self, user_id: int, scan_id: int) -> None:
        with closing(self._get_connection()) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM ats_scan_history WHERE id = %s AND user_id = %s",
                (scan_id, user_id),
            )
            conn.commit()

            if cursor.rowcount == 0:
                raise ValueError("Scan history item not found")

    def get_scan_usage(self, user_id: int) -> dict[str, Any]:
        scan_day = self._today_utc_date()

        with closing(self._get_connection()) as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT scan_count
                FROM ats_scan_usage
                WHERE user_id = %s AND scan_date = %s
                LIMIT 1
                """,
                (user_id, scan_day),
            )
            row = cursor.fetchone()

        used_today = int((row or {}).get("scan_count") or 0)
        remaining_today = max(0, self.DAILY_SCAN_LIMIT - used_today)

        return {
            "daily_limit": self.DAILY_SCAN_LIMIT,
            "used_today": used_today,
            "remaining_today": remaining_today,
            "reset_at_utc": self._next_utc_midnight(),
        }

    def _check_ats_with_rules(self, payload: ATSCheckRequest) -> ATSCheckResponse:
        resume_tokens = self._extract_keywords(payload.resume_text)
        jd_tokens = self._extract_keywords(payload.job_description)

        matched = sorted(jd_tokens.intersection(resume_tokens))
        missing = sorted(jd_tokens.difference(resume_tokens))

        keyword_match_score = self._safe_percentage(len(matched), max(len(jd_tokens), 1))
        section_score, section_gaps = self._evaluate_sections(payload.resume_text)
        readability_score = self._readability_score(payload.resume_text)
        uae_fit_score = self._uae_fit_score(payload.resume_text, payload.job_description)

        overall = round(
            (
                (keyword_match_score * 0.45)
                + (section_score * 0.20)
                + (readability_score * 0.15)
                + (uae_fit_score * 0.20)
            ),
            2,
        )

        recommendations = self._build_recommendations(
            missing_keywords=missing,
            section_gaps=section_gaps,
            readability_score=readability_score,
            uae_fit_score=uae_fit_score,
        )

        return ATSCheckResponse(
            overall_score=overall,
            breakdown=ScoreBreakdown(
                keyword_match=keyword_match_score,
                section_completeness=section_score,
                readability=readability_score,
                uae_market_fit=uae_fit_score,
            ),
            missing_keywords=missing[:25],
            matched_keywords=matched[:25],
            section_gaps=section_gaps,
            recommendations=recommendations,
        )

    def _check_ats_with_gemini(self, payload: ATSCheckRequest) -> ATSCheckResponse:
        if not self.gemini_api_key:
            raise GeminiUnavailableError("Gemini API is not configured. Set GEMINI_API_KEY on the server.")

        prompt = self._build_gemini_ats_prompt(payload)
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.gemini_model}:generateContent"

        try:
            response = requests.post(
                url,
                params={"key": self.gemini_api_key},
                json={
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {
                        "responseMimeType": "application/json",
                        "temperature": 0.2,
                    },
                },
                timeout=30,
            )
            response.raise_for_status()
            model_text = self._extract_gemini_text(response.json())
            if not model_text:
                raise GeminiUnavailableError("Gemini returned an empty response. Please try again.")

            parsed = self._parse_gemini_ats_json(model_text)
            if parsed is None:
                raise GeminiUnavailableError("Gemini returned an invalid response format. Please try again.")

            return parsed
        except requests.Timeout as exc:
            raise GeminiUnavailableError("Gemini request timed out. Please try again.") from exc
        except requests.HTTPError as exc:
            status_code = exc.response.status_code if exc.response is not None else "unknown"
            provider_message = ""
            if exc.response is not None:
                try:
                    payload = exc.response.json()
                    provider_message = str(payload.get("error", {}).get("message", "")).strip()
                except ValueError:
                    provider_message = (exc.response.text or "").strip()

            detail = f"Gemini request failed ({status_code})."
            if provider_message:
                detail = f"{detail} {provider_message}"

            raise GeminiUnavailableError(detail) from exc
        except requests.RequestException as exc:
            raise GeminiUnavailableError("Gemini is currently unreachable. Please try again shortly.") from exc

    def optimize_resume(self, payload: ResumeOptimizeRequest) -> ResumeOptimizeResponse:
        resume_lines = [line.strip() for line in payload.resume_text.splitlines() if line.strip()]
        rewritten_bullets = self._rewrite_bullets_for_impact(resume_lines)

        skills_to_add: List[str] = []
        if payload.job_description:
            gap = self.keyword_gap(
                KeywordGapRequest(
                    resume_text=payload.resume_text,
                    job_description=payload.job_description,
                )
            )
            skills_to_add = gap.high_priority_keywords[:10]

        optimized_summary = self._build_uae_summary(
            payload.resume_text,
            payload.target_role,
            payload.preferred_emirate,
        )

        tips = self._uae_localization_tips(payload.resume_text, payload.preferred_emirate)

        return ResumeOptimizeResponse(
            optimized_summary=optimized_summary,
            rewritten_bullets=rewritten_bullets[:8],
            skills_to_add=skills_to_add,
            uae_localization_tips=tips,
        )

    def keyword_gap(self, payload: KeywordGapRequest) -> KeywordGapResponse:
        resume_tokens = self._extract_keywords(payload.resume_text)
        jd_tokens = self._extract_keywords(payload.job_description)

        missing = sorted(jd_tokens - resume_tokens)
        token_freq = self._token_frequency(payload.job_description)
        high_priority = [token for token, _ in token_freq if token in missing][:15]

        matched = len(jd_tokens.intersection(resume_tokens))
        coverage = round(self._safe_percentage(matched, max(len(jd_tokens), 1)), 2)

        return KeywordGapResponse(
            missing_keywords=missing[:30],
            high_priority_keywords=high_priority,
            coverage_percentage=coverage,
        )

    async def extract_resume_text(self, file: UploadFile) -> ResumeExtractResponse:
        if not file.filename:
            raise ValueError("File name is required")

        file_bytes = await file.read()
        return self.extract_resume_text_from_bytes(file.filename, file_bytes)

    def extract_resume_text_from_bytes(self, file_name: str, file_bytes: bytes) -> ResumeExtractResponse:
        extension = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else ""
        if extension not in self.SUPPORTED_FILE_TYPES:
            raise ValueError("Only PDF and DOCX files are supported")

        if not file_bytes:
            raise ValueError("Uploaded file is empty")

        try:
            if extension == "pdf":
                extracted_text = self._extract_text_from_pdf(file_bytes)
            else:
                extracted_text = self._extract_text_from_docx(file_bytes)
        except Exception as exc:  # parser-level errors
            raise ValueError("Unable to parse the uploaded file. Please upload a valid PDF or DOCX.") from exc

        normalized_text = re.sub(r"\s+", " ", extracted_text).strip()
        if not normalized_text:
            raise ValueError("Could not extract readable text from the uploaded file")

        return ResumeExtractResponse(
            file_name=file_name,
            file_type=extension,
            extracted_text=normalized_text,
            character_count=len(normalized_text),
        )

    def _extract_text_from_pdf(self, file_bytes: bytes) -> str:
        reader = PdfReader(BytesIO(file_bytes))
        pages = [page.extract_text() or "" for page in reader.pages]
        return "\n".join(pages)

    def _build_gemini_ats_prompt(self, payload: ATSCheckRequest) -> str:
        return (
            "You are an ATS evaluator for UAE hiring. Analyze the resume against the job description. "
            "Return ONLY valid JSON with this exact schema and no extra keys: "
            "{\"overall_score\": number, \"breakdown\": {\"keyword_match\": number, \"section_completeness\": number, \"readability\": number, \"uae_market_fit\": number}, "
            "\"missing_keywords\": string[], \"matched_keywords\": string[], \"section_gaps\": string[], \"recommendations\": string[]}. "
            "All scores must be between 0 and 100. Keep keyword arrays concise (max 25 each). Keep recommendations practical (max 8).\n\n"
            f"Target Role: {payload.target_role or 'N/A'}\n"
            f"Industry: {payload.industry or 'N/A'}\n\n"
            f"Job Description:\n{payload.job_description}\n\n"
            f"Resume:\n{payload.resume_text}"
        )

    @staticmethod
    def _extract_gemini_text(raw_response: dict[str, Any]) -> str:
        candidates = raw_response.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            return ""

        first = candidates[0] if isinstance(candidates[0], dict) else {}
        content = first.get("content") if isinstance(first, dict) else {}
        parts = content.get("parts") if isinstance(content, dict) else []
        if not isinstance(parts, list):
            return ""

        chunks: list[str] = []
        for part in parts:
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                chunks.append(part["text"])
        return "\n".join(chunks).strip()

    def _parse_gemini_ats_json(self, text: str) -> ATSCheckResponse | None:
        cleaned = text.strip()

        if "```" in cleaned:
            cleaned = cleaned.replace("```json", "").replace("```", "").strip()

        start_idx = cleaned.find("{")
        end_idx = cleaned.rfind("}")
        if start_idx == -1 or end_idx == -1 or end_idx <= start_idx:
            return None

        json_text = cleaned[start_idx : end_idx + 1]

        try:
            data = json.loads(json_text)
        except json.JSONDecodeError:
            return None

        try:
            breakdown_raw = data.get("breakdown") if isinstance(data, dict) else {}
            breakdown = ScoreBreakdown(
                keyword_match=self._normalize_score(breakdown_raw.get("keyword_match")),
                section_completeness=self._normalize_score(breakdown_raw.get("section_completeness")),
                readability=self._normalize_score(breakdown_raw.get("readability")),
                uae_market_fit=self._normalize_score(breakdown_raw.get("uae_market_fit")),
            )

            return ATSCheckResponse(
                overall_score=self._normalize_score(data.get("overall_score")),
                breakdown=breakdown,
                missing_keywords=self._normalize_text_list(data.get("missing_keywords"), 25),
                matched_keywords=self._normalize_text_list(data.get("matched_keywords"), 25),
                section_gaps=self._normalize_text_list(data.get("section_gaps"), 12),
                recommendations=self._normalize_text_list(data.get("recommendations"), 8),
            )
        except Exception:
            return None

    @staticmethod
    def _normalize_score(value: Any) -> float:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            numeric = 0.0
        return round(max(0.0, min(100.0, numeric)), 2)

    @staticmethod
    def _normalize_text_list(value: Any, limit: int) -> list[str]:
        if not isinstance(value, list):
            return []

        normalized: list[str] = []
        for item in value:
            if not isinstance(item, str):
                continue
            cleaned = item.strip()
            if cleaned:
                normalized.append(cleaned)
            if len(normalized) >= limit:
                break

        return normalized

    def _consume_scan_quota(self, user_id: int) -> None:
        scan_day = self._today_utc_date()

        with closing(self._get_connection()) as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT scan_count
                FROM ats_scan_usage
                WHERE user_id = %s AND scan_date = %s
                FOR UPDATE
                """,
                (user_id, scan_day),
            )
            row = cursor.fetchone()

            if row is None:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO ats_scan_usage (user_id, scan_date, scan_count, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (user_id, scan_day, 1, self._now_utc(), self._now_utc()),
                )
                conn.commit()
                return

            current_count = int(row.get("scan_count") or 0)
            if current_count >= self.DAILY_SCAN_LIMIT:
                raise ScanLimitExceededError(
                    f"Daily ATS scan limit reached ({self.DAILY_SCAN_LIMIT}/day). Please try again tomorrow."
                )

            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE ats_scan_usage
                SET scan_count = scan_count + 1, updated_at = %s
                WHERE user_id = %s AND scan_date = %s
                """,
                (self._now_utc(), user_id, scan_day),
            )
            conn.commit()

    def _save_scan_history(self, user_id: int, payload: ATSCheckRequest, result: ATSCheckResponse) -> None:
        resume_file_name = self._normalize_optional_short_text(payload.resume_file_name, max_length=255)
        resume_file_type = self._normalize_optional_short_text(payload.resume_file_type, max_length=16)
        target_role = self._normalize_optional_short_text(payload.target_role, max_length=255)
        industry = self._normalize_optional_short_text(payload.industry, max_length=255)

        with closing(self._get_connection()) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO ats_scan_history (
                    user_id,
                    resume_id,
                    resume_file_name,
                    resume_file_type,
                    target_role,
                    industry,
                    resume_text_snapshot,
                    job_description_snapshot,
                    overall_score,
                    breakdown_json,
                    matched_keywords_json,
                    missing_keywords_json,
                    section_gaps_json,
                    recommendations_json,
                    matched_keywords_count,
                    missing_keywords_count,
                    section_gaps_count,
                    summary,
                    created_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    user_id,
                    payload.resume_id,
                    resume_file_name,
                    resume_file_type,
                    target_role,
                    industry,
                    payload.resume_text,
                    payload.job_description,
                    result.overall_score,
                    json.dumps(result.breakdown.model_dump()),
                    json.dumps(result.matched_keywords),
                    json.dumps(result.missing_keywords),
                    json.dumps(result.section_gaps),
                    json.dumps(result.recommendations),
                    len(result.matched_keywords),
                    len(result.missing_keywords),
                    len(result.section_gaps),
                    self._build_scan_summary(payload, result),
                    self._now_utc(),
                ),
            )
            conn.commit()

    def _build_scan_summary(self, payload: ATSCheckRequest, result: ATSCheckResponse) -> str:
        resume_label = (payload.resume_file_name or "Your CV").strip() or "Your CV"
        role_label = (payload.target_role or "target role").strip() or "target role"
        return (
            f"{resume_label} vs {role_label}: "
            f"{len(result.matched_keywords)} matched keywords, "
            f"{len(result.missing_keywords)} missing, "
            f"{len(result.section_gaps)} section gaps."
        )

    def _extract_text_from_docx(self, file_bytes: bytes) -> str:
        document = Document(BytesIO(file_bytes))
        return "\n".join(paragraph.text for paragraph in document.paragraphs)

    def _extract_keywords(self, text: str) -> Set[str]:
        tokens = re.findall(r"[A-Za-z][A-Za-z\-\+\.]{1,}", text.lower())
        cleaned = {token.strip("-+.") for token in tokens}
        return {
            token
            for token in cleaned
            if len(token) > 2 and token not in self.STOPWORDS and not token.isnumeric()
        }

    def _token_frequency(self, text: str) -> List[Tuple[str, int]]:
        tokens = re.findall(r"[A-Za-z][A-Za-z\-\+\.]{1,}", text.lower())
        filtered = [
            token.strip("-+.")
            for token in tokens
            if len(token) > 2 and token not in self.STOPWORDS
        ]
        counts = Counter(filtered)
        return sorted(counts.items(), key=lambda item: item[1], reverse=True)

    def _evaluate_sections(self, resume_text: str) -> Tuple[float, List[str]]:
        lower_resume = resume_text.lower()
        gaps = [section for section in self.REQUIRED_SECTIONS if section not in lower_resume]
        score = round(((len(self.REQUIRED_SECTIONS) - len(gaps)) / len(self.REQUIRED_SECTIONS)) * 100, 2)
        return score, gaps

    def _readability_score(self, resume_text: str) -> float:
        words = resume_text.split()
        lines = [line for line in resume_text.splitlines() if line.strip()]
        if not words:
            return 0.0

        avg_words_per_line = len(words) / max(len(lines), 1)
        if avg_words_per_line <= 14:
            return 90.0
        if avg_words_per_line <= 20:
            return 75.0
        if avg_words_per_line <= 28:
            return 60.0
        return 45.0

    def _uae_fit_score(self, resume_text: str, job_description: str) -> float:
        combined = f"{resume_text.lower()} {job_description.lower()}"
        matches = sum(1 for keyword in self.UAE_KEYWORDS if keyword in combined)
        return round(self._safe_percentage(matches, len(self.UAE_KEYWORDS)), 2)

    def _build_recommendations(
        self,
        missing_keywords: List[str],
        section_gaps: List[str],
        readability_score: float,
        uae_fit_score: float,
    ) -> List[str]:
        recommendations: List[str] = []

        if missing_keywords:
            recommendations.append(
                "Add missing job keywords naturally in your experience and skills sections."
            )
        if section_gaps:
            recommendations.append(
                f"Include missing sections: {', '.join(section_gaps)}."
            )
        if readability_score < 70:
            recommendations.append(
                "Use shorter bullet points with measurable outcomes for better ATS readability."
            )
        if uae_fit_score < 30:
            recommendations.append(
                "Add UAE/GCC context like local regulations, visa status, or regional project exposure."
            )

        if not recommendations:
            recommendations.append("Resume is ATS-friendly. Fine-tune with role-specific achievements.")

        return recommendations

    def _rewrite_bullets_for_impact(self, resume_lines: List[str]) -> List[str]:
        action_verbs = [
            "Led",
            "Delivered",
            "Optimized",
            "Implemented",
            "Automated",
            "Improved",
            "Reduced",
            "Increased",
        ]
        rewritten: List[str] = []

        for index, line in enumerate(resume_lines[:12]):
            if len(line.split()) < 4:
                continue
            verb = action_verbs[index % len(action_verbs)]
            sentence = line.rstrip(".")
            rewritten.append(f"{verb} {sentence} with measurable impact across KPIs.")

        return rewritten

    def _build_uae_summary(
        self,
        resume_text: str,
        target_role: str | None,
        preferred_emirate: str | None,
    ) -> str:
        role_text = target_role or "target role"
        emirate_text = preferred_emirate or "UAE"

        top_skills = sorted(self._extract_keywords(resume_text))[:6]
        skill_text = ", ".join(top_skills[:4]) if top_skills else "cross-functional execution"

        return (
            f"Results-driven professional targeting {role_text} opportunities in {emirate_text}, "
            f"with strengths in {skill_text}. Proven ability to deliver business outcomes in "
            "fast-paced, multicultural environments aligned with UAE market expectations."
        )

    def _uae_localization_tips(self, resume_text: str, preferred_emirate: str | None) -> List[str]:
        lower_resume = resume_text.lower()
        tips = []

        if "visa" not in lower_resume:
            tips.append("Add work authorization/visa status for UAE recruiters.")
        if "phone" not in lower_resume and "mobile" not in lower_resume:
            tips.append("Include UAE-reachable contact number with country code.")
        if "linkedin" not in lower_resume:
            tips.append("Add an updated LinkedIn URL.")

        tips.append(
            f"Tailor achievements for hiring trends in {preferred_emirate or 'Dubai/Abu Dhabi'} sectors."
        )
        tips.append("Highlight region-relevant tools, standards, or compliance exposure when applicable.")

        return tips[:6]

    @staticmethod
    def _safe_percentage(part: int | float, whole: int | float) -> float:
        if whole == 0:
            return 0.0
        return round((part / whole) * 100, 2)

    @staticmethod
    def _normalize_optional_short_text(value: str | None, max_length: int) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            return None
        return normalized[:max_length]

    @staticmethod
    def _parse_json_object(value: Any) -> dict[str, float]:
        default = {
            "keyword_match": 0.0,
            "section_completeness": 0.0,
            "readability": 0.0,
            "uae_market_fit": 0.0,
        }
        if not value:
            return default

        try:
            parsed = json.loads(value)
        except (TypeError, json.JSONDecodeError):
            return default

        if not isinstance(parsed, dict):
            return default

        result = default.copy()
        for key in result:
            try:
                result[key] = float(parsed.get(key, 0.0))
            except (TypeError, ValueError):
                result[key] = 0.0
        return result

    @staticmethod
    def _parse_json_string_list(value: Any) -> list[str]:
        if not value:
            return []

        try:
            parsed = json.loads(value)
        except (TypeError, json.JSONDecodeError):
            return []

        if not isinstance(parsed, list):
            return []

        cleaned: list[str] = []
        for item in parsed:
            if isinstance(item, str):
                normalized = item.strip()
                if normalized:
                    cleaned.append(normalized)
        return cleaned

    @staticmethod
    def _coerce_long_text(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        return str(value)

    def _get_connection(self, include_database: bool = True) -> MySQLConnectionAbstract:
        config = {
            "host": self.db_config["host"],
            "port": self.db_config["port"],
            "user": self.db_config["user"],
            "password": self.db_config["password"],
        }

        if include_database:
            config["database"] = self.db_config["database"]

        return mysql.connector.connect(**config)

    @staticmethod
    def _resolve_db_config() -> dict[str, Any]:
        host = os.getenv("MYSQL_HOST", "localhost")
        port = int(os.getenv("MYSQL_PORT", "3306"))
        user = os.getenv("MYSQL_USER", "root")
        password = os.getenv("MYSQL_PASSWORD", "")
        database = os.getenv("MYSQL_DATABASE", "talent_probe")

        return {
            "host": host,
            "port": port,
            "user": user,
            "password": password,
            "database": database,
        }

    @staticmethod
    def _today_utc_date() -> date:
        return datetime.now(timezone.utc).date()

    @staticmethod
    def _next_utc_midnight() -> datetime:
        now = datetime.now(timezone.utc)
        tomorrow = (now + timedelta(days=1)).date()
        return datetime.combine(tomorrow, datetime.min.time(), tzinfo=timezone.utc).replace(tzinfo=None)

    @staticmethod
    def _now_utc() -> datetime:
        return datetime.now(timezone.utc).replace(tzinfo=None)


class ScanLimitExceededError(ValueError):
    pass


class GeminiUnavailableError(ValueError):
    pass
