// Talent Probe UAE — API Client
// Centralized HTTP client with auth interceptor

const BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000';

// ─── Types ───────────────────────────────────────────────────────────────────

export interface ApiResponse<T = unknown> {
  success: boolean;
  data: T;
  message?: string;
}

export interface AuthTokens {
  access_token: string;
}

export interface RegisteredUser {
  user_id: number;
  full_name: string;
  email: string;
  profile_image_url?: string | null;
}

export interface CandidateProfile {
  user_id: number;
  full_name: string;
  email: string;
  profile_image_url?: string | null;
  dob?: string | null;
  current_organization?: string | null;
  current_role?: string | null;
  experience_years?: number | null;
  linkedin_url?: string | null;
  github_url?: string | null;
  twitter_url?: string | null;
}

export interface CandidateProfileUpdatePayload {
  full_name: string;
  dob?: string | null;
  current_organization?: string | null;
  current_role?: string | null;
  experience_years?: number | null;
  linkedin_url?: string | null;
  github_url?: string | null;
  twitter_url?: string | null;
}

export interface ResumeLibraryItem {
  resume_id: number;
  file_name: string;
  file_type: 'pdf' | 'docx' | string;
  character_count: number;
  created_at: string;
}

export interface ResumeLibraryItemDetail extends ResumeLibraryItem {
  extracted_text: string;
  storage_provider: string;
  file_url?: string | null;
}

export interface ResumeExtractResult {
  file_name: string;
  file_type: 'pdf' | 'docx';
  extracted_text: string;
  character_count: number;
}

export interface RegisterPayload {
  full_name: string;
  email: string;
  password: string;
}

export interface LoginPayload {
  email: string;
  password: string;
}

export interface GoogleAuthPayload {
  id_token: string;
}

export interface ATSCheckPayload {
  resume_text: string;
  job_description: string;
  target_role?: string;
  industry?: string;
  resume_id?: number;
  resume_file_name?: string;
  resume_file_type?: string;
}

export interface ATSCheckResult {
  overall_score: number;
  breakdown?: Record<string, number>;
  score_breakdown?: Record<string, number>;
  matched_keywords?: string[];
  missing_keywords?: string[];
  section_gaps?: string[];
  recommendations?: string[];
  [key: string]: unknown;
}

export interface ATSUsage {
  daily_limit: number;
  used_today: number;
  remaining_today: number;
  reset_at_utc: string;
}

export interface ATSScanHistoryItem {
  scan_id: number;
  resume_id?: number | null;
  resume_file_name?: string | null;
  resume_file_type?: string | null;
  target_role?: string | null;
  industry?: string | null;
  resume_text_snapshot: string;
  job_description_snapshot: string;
  overall_score: number;
  breakdown: Record<string, number>;
  matched_keywords: string[];
  missing_keywords: string[];
  section_gaps: string[];
  recommendations: string[];
  matched_keywords_count: number;
  missing_keywords_count: number;
  section_gaps_count: number;
  summary: string;
  created_at: string;
}

export interface ResumeOptimizePayload {
  resume_text: string;
  job_description?: string;
  target_role?: string;
  preferred_emirate?: string;
}

export interface ResumeOptimizeResult {
  optimized_summary?: string;
  rewritten_bullets?: string[];
  skills_to_add?: string[];
  uae_localization_tips?: string[];
  [key: string]: unknown;
}

export interface KeywordGapPayload {
  resume_text: string;
  job_description: string;
}

export interface KeywordGapResult {
  missing_keywords?: string[];
  high_priority_keywords?: string[];
  coverage_percentage?: number;
  [key: string]: unknown;
}

// ─── Token storage ────────────────────────────────────────────────────────────

const TOKEN_KEY = 'talent_probe_token';

export const tokenStore = {
  get: (): string | null => localStorage.getItem(TOKEN_KEY),
  set: (token: string) => localStorage.setItem(TOKEN_KEY, token),
  clear: () => localStorage.removeItem(TOKEN_KEY),
};

// ─── Core fetch wrapper ───────────────────────────────────────────────────────

class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

async function request<T>(
  path: string,
  options: RequestInit = {},
  authenticated = false
): Promise<T> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string>),
  };

  if (authenticated) {
    const token = tokenStore.get();
    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }
  }

  const response = await fetch(`${BASE_URL}${path}`, {
    ...options,
    headers,
  });

  if (response.status === 401) {
    tokenStore.clear();
    window.dispatchEvent(new CustomEvent('auth:unauthorized'));
    throw new ApiError('Session expired. Please log in again.', 401);
  }

  const json = await response.json();

  if (!response.ok) {
    const message =
      json?.detail ||
      json?.message ||
      json?.error ||
      `Request failed (${response.status})`;
    throw new ApiError(message, response.status);
  }

  return json as T;
}

async function uploadRequest<T>(path: string, file: File): Promise<T> {
  const formData = new FormData();
  formData.append('file', file);

  const headers: Record<string, string> = {};
  const token = tokenStore.get();
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const response = await fetch(`${BASE_URL}${path}`, {
    method: 'POST',
    headers,
    body: formData,
  });

  if (response.status === 401) {
    tokenStore.clear();
    window.dispatchEvent(new CustomEvent('auth:unauthorized'));
    throw new ApiError('Session expired. Please log in again.', 401);
  }

  const json = await response.json();
  if (!response.ok) {
    const message =
      json?.detail ||
      json?.message ||
      json?.error ||
      `Request failed (${response.status})`;
    throw new ApiError(message, response.status);
  }

  return json as T;
}

async function downloadRequest(path: string): Promise<{ blob: Blob; fileName?: string }> {
  const headers: Record<string, string> = {};
  const token = tokenStore.get();
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const response = await fetch(`${BASE_URL}${path}`, {
    method: 'GET',
    headers,
  });

  if (response.status === 401) {
    tokenStore.clear();
    window.dispatchEvent(new CustomEvent('auth:unauthorized'));
    throw new ApiError('Session expired. Please log in again.', 401);
  }

  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try {
      const json = await response.json();
      message = json?.detail || json?.message || json?.error || message;
    } catch {
      message = response.statusText || message;
    }
    throw new ApiError(message, response.status);
  }

  const blob = await response.blob();
  const contentDisposition = response.headers.get('content-disposition') || '';
  let fileName: string | undefined;

  const filenameStarMatch = contentDisposition.match(/filename\*=UTF-8''([^;]+)/i);
  if (filenameStarMatch?.[1]) {
    try {
      fileName = decodeURIComponent(filenameStarMatch[1]);
    } catch {
      fileName = filenameStarMatch[1];
    }
  }

  if (!fileName) {
    const filenameMatch = contentDisposition.match(/filename="?([^";]+)"?/i);
    fileName = filenameMatch?.[1];
  }

  return {
    blob,
    fileName,
  };
}

// ─── Endpoints ────────────────────────────────────────────────────────────────

export const api = {
  health: () =>
    request<ApiResponse<{ status: string }>>('/api/v1/health'),

  auth: {
    register: (payload: RegisterPayload) =>
      request<ApiResponse<RegisteredUser>>('/api/v1/auth/register', {
        method: 'POST',
        body: JSON.stringify(payload),
      }),

    login: (payload: LoginPayload) =>
      request<ApiResponse<AuthTokens>>('/api/v1/auth/login', {
        method: 'POST',
        body: JSON.stringify(payload),
      }),

    google: (payload: GoogleAuthPayload) =>
      request<ApiResponse<AuthTokens>>('/api/v1/auth/google', {
        method: 'POST',
        body: JSON.stringify(payload),
      }),

    me: () =>
      request<ApiResponse<RegisteredUser>>('/api/v1/auth/me', {
        method: 'GET',
      }, true),
  },

  ats: {
    usage: () =>
      request<ApiResponse<ATSUsage>>('/api/v1/ats/usage', {
        method: 'GET',
      }, true),

    history: () =>
      request<ApiResponse<ATSScanHistoryItem[]>>('/api/v1/ats/history', {
        method: 'GET',
      }, true),

    deleteHistoryItem: (scanId: number) =>
      request<ApiResponse<{ deleted: boolean; scan_id: number }>>(`/api/v1/ats/history/${scanId}`, {
        method: 'DELETE',
      }, true),

    check: (payload: ATSCheckPayload) =>
      request<ApiResponse<ATSCheckResult>>('/api/v1/ats/check', {
        method: 'POST',
        body: JSON.stringify(payload),
      }, true),
  },

  resume: {
    extractText: (file: File) =>
      uploadRequest<ApiResponse<ResumeExtractResult>>('/api/v1/resume/extract-text', file),

    optimize: (payload: ResumeOptimizePayload) =>
      request<ApiResponse<ResumeOptimizeResult>>('/api/v1/resume/optimize', {
        method: 'POST',
        body: JSON.stringify(payload),
      }, true),

    keywordGap: (payload: KeywordGapPayload) =>
      request<ApiResponse<KeywordGapResult>>('/api/v1/resume/keyword-gap', {
        method: 'POST',
        body: JSON.stringify(payload),
      }, true),
  },

  profile: {
    get: () =>
      request<ApiResponse<CandidateProfile>>('/api/v1/profile', {
        method: 'GET',
      }, true),

    update: (payload: CandidateProfileUpdatePayload) =>
      request<ApiResponse<CandidateProfile>>('/api/v1/profile', {
        method: 'PUT',
        body: JSON.stringify(payload),
      }, true),
  },

  resumes: {
    list: () =>
      request<ApiResponse<ResumeLibraryItem[]>>('/api/v1/resumes', {
        method: 'GET',
      }, true),

    get: (resumeId: number) =>
      request<ApiResponse<ResumeLibraryItemDetail>>(`/api/v1/resumes/${resumeId}`, {
        method: 'GET',
      }, true),

    upload: (file: File) =>
      uploadRequest<ApiResponse<ResumeLibraryItemDetail>>('/api/v1/resumes/upload', file),

    delete: (resumeId: number) =>
      request<ApiResponse<{ deleted: boolean; resume_id: number }>>(`/api/v1/resumes/${resumeId}`, {
        method: 'DELETE',
      }, true),

    download: (resumeId: number) =>
      downloadRequest(`/api/v1/resumes/${resumeId}/download`),
  },
};
