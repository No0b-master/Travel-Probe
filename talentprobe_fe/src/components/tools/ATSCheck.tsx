import { useEffect, useState, type ReactNode } from 'react';
import { Eye, Trash2 } from 'lucide-react';
import { api, type ATSCheckResult, type ATSScanHistoryItem, type ATSUsage } from '@/lib/api';
import { useToast } from '@/hooks/use-toast';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { ResultBlock, ScoreBar, KeywordChips, BulletList } from '@/components/ResultComponents';
import { cn } from '@/lib/utils';
import { ResumeLibrarySelector } from '@/components/ResumeLibrarySelector';
import { ResumeDocumentViewer } from '@/components/ResumeDocumentViewer';

// ─── Score circle ──────────────────────────────────────────────────────────────

function ScoreCircle({ score }: { score: number }) {
  const clamped = Math.min(100, Math.max(0, score));
  const color =
    clamped >= 70 ? 'text-green-500' : clamped >= 40 ? 'text-amber-500' : 'text-red-500';
  const label =
    clamped >= 70 ? 'Great' : clamped >= 40 ? 'Fair' : 'Needs Work';

  return (
    <div className="flex flex-col items-center justify-center gap-1 py-2">
      <div
        className={cn(
          'flex h-28 w-28 flex-col items-center justify-center rounded-full border-4 bg-card shadow-brand-md',
          clamped >= 70
            ? 'border-green-400'
            : clamped >= 40
            ? 'border-amber-400'
            : 'border-red-400'
        )}
      >
        <span className={cn('text-3xl font-bold', color)}>{clamped}</span>
        <span className="text-xs font-medium text-muted-foreground">/ 100</span>
      </div>
      <span className={cn('text-sm font-semibold', color)}>{label}</span>
    </div>
  );
}

function formatScoreLabel(label: string): string {
  return label
    .replace(/_/g, ' ')
    .split(' ')
    .filter(Boolean)
    .map(word => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase())
    .join(' ');
}

// ─── Results view ──────────────────────────────────────────────────────────────

function ATSResults({ result }: { result: ATSCheckResult }) {
  const breakdown = result.breakdown ?? result.score_breakdown ?? {};
  const matched = result.matched_keywords ?? [];
  const missing = result.missing_keywords ?? [];
  const gaps = result.section_gaps ?? [];
  const recs = result.recommendations ?? [];

  const summaryText = [
    `ATS Overall Score: ${result.overall_score}/100`,
    '',
    'Matched Keywords: ' + matched.join(', '),
    'Missing Keywords: ' + missing.join(', '),
    '',
    'Section Gaps: ' + gaps.join(', '),
    '',
    'Recommendations:',
    ...recs.map((r, i) => `${i + 1}. ${r}`),
  ].join('\n');

  return (
    <div className="space-y-4 animate-fade-up">
      {/* Score */}
      <ResultBlock label="Overall ATS Score">
        <div className="flex flex-col sm:flex-row items-center gap-6">
          <ScoreCircle score={result.overall_score} />
          {Object.keys(breakdown).length > 0 && (
            <div className="flex-1 w-full space-y-3">
              {Object.entries(breakdown).map(([key, val]) => (
                <ScoreBar key={key} label={formatScoreLabel(key)} value={val} />
              ))}
            </div>
          )}
        </div>
      </ResultBlock>

      {/* Keywords */}
      <div className="grid sm:grid-cols-2 gap-4">
        <ResultBlock label={`Matched Keywords (${matched.length})`} copyText={matched.join(', ')}>
          <KeywordChips keywords={matched} variant="matched" />
        </ResultBlock>
        <ResultBlock label={`Missing Keywords (${missing.length})`} copyText={missing.join(', ')}>
          <KeywordChips keywords={missing} variant="missing" />
        </ResultBlock>
      </div>

      {/* Gaps & Recommendations */}
      {gaps.length > 0 && (
        <ResultBlock label="Section Gaps" copyText={gaps.join('\n')}>
          <KeywordChips keywords={gaps} variant="priority" />
        </ResultBlock>
      )}

      {recs.length > 0 && (
        <ResultBlock label="Recommendations" copyText={summaryText}>
          <BulletList items={recs} />
        </ResultBlock>
      )}
    </div>
  );
}

function AIScanAnimation() {
  return (
    <ResultBlock label="AI Scan In Progress">
      <div className="space-y-3">
        <div className="flex items-center gap-3">
          <span className="inline-flex h-3 w-3 animate-ping rounded-full bg-primary" />
          <p className="text-sm font-medium text-foreground">Gemini is analyzing your resume against the job description...</p>
        </div>
        <div className="h-2 w-full overflow-hidden rounded-full bg-muted">
          <div className="h-full w-1/3 animate-pulse rounded-full bg-primary" />
        </div>
        <div className="grid grid-cols-3 gap-2">
          <div className="h-16 animate-pulse rounded-md border border-border bg-background" />
          <div className="h-16 animate-pulse rounded-md border border-border bg-background" />
          <div className="h-16 animate-pulse rounded-md border border-border bg-background" />
        </div>
      </div>
    </ResultBlock>
  );
}

// ─── Main component ───────────────────────────────────────────────────────────

export function ATSCheck() {
  const { toast } = useToast();
  const [form, setForm] = useState({
    resume_text: '',
    job_description: '',
    target_role: '',
    industry: '',
  });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<ATSCheckResult | null>(null);
  const [usage, setUsage] = useState<ATSUsage | null>(null);
  const [usageLoading, setUsageLoading] = useState(true);
  const [history, setHistory] = useState<ATSScanHistoryItem[]>([]);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [deletingScanId, setDeletingScanId] = useState<number | null>(null);
  const [viewingDeletedCVSnapshot, setViewingDeletedCVSnapshot] = useState(false);
  const [selectedResumeMeta, setSelectedResumeMeta] = useState<{
    resumeId: number;
    fileName: string;
    fileType: string;
  } | null>(null);

  const loadUsage = async () => {
    setUsageLoading(true);
    try {
      const res = await api.ats.usage();
      if (res.success) {
        setUsage(res.data);
      }
    } catch {
      setUsage(null);
    } finally {
      setUsageLoading(false);
    }
  };

  const loadHistory = async () => {
    setHistoryLoading(true);
    try {
      const res = await api.ats.history();
      if (res.success) {
        setHistory(res.data);
      }
    } catch {
      setHistory([]);
    } finally {
      setHistoryLoading(false);
    }
  };

  useEffect(() => {
    void loadUsage();
    void loadHistory();
  }, []);

  const set = (key: string) => (
    e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>
  ) => {
    setForm(prev => ({ ...prev, [key]: e.target.value }));
    setErrors(prev => ({ ...prev, [key]: '' }));
  };

  const validate = () => {
    const e: Record<string, string> = {};
    if (!form.resume_text.trim() || form.resume_text.trim().length < 50)
      e.resume_text = 'Resume text must be at least 50 characters';
    if (!form.job_description.trim() || form.job_description.trim().length < 30)
      e.job_description = 'Job description must be at least 30 characters';
    setErrors(e);
    return !Object.keys(e).length;
  };

  const handleSubmit = async (ev: React.FormEvent) => {
    ev.preventDefault();
    if (!validate()) return;
    setLoading(true);
    setResult(null);
    setViewingDeletedCVSnapshot(false);
    try {
      const res = await api.ats.check({
        resume_text: form.resume_text.trim(),
        job_description: form.job_description.trim(),
        ...(form.target_role.trim() && { target_role: form.target_role.trim() }),
        ...(form.industry.trim() && { industry: form.industry.trim() }),
        ...(selectedResumeMeta?.resumeId && { resume_id: selectedResumeMeta.resumeId }),
        ...(selectedResumeMeta?.fileName && { resume_file_name: selectedResumeMeta.fileName }),
        ...(selectedResumeMeta?.fileType && { resume_file_type: selectedResumeMeta.fileType }),
      });
      if (res.success) {
        setResult(res.data);
        toast({ title: 'ATS check complete ✓' });
        void loadHistory();
      }
    } catch (err: unknown) {
      toast({
        title: 'ATS check failed',
        description: err instanceof Error ? err.message : 'Something went wrong',
        variant: 'destructive',
      });
    } finally {
      setLoading(false);
      void loadUsage();
    }
  };

  const handleDeleteScan = async (scanId: number) => {
    setDeletingScanId(scanId);
    try {
      const res = await api.ats.deleteHistoryItem(scanId);
      if (res.success) {
        setHistory(prev => prev.filter(item => item.scan_id !== scanId));
        toast({ title: 'Scan removed' });
      }
    } catch (err: unknown) {
      toast({
        title: 'Unable to delete scan',
        description: err instanceof Error ? err.message : 'Please try again',
        variant: 'destructive',
      });
    } finally {
      setDeletingScanId(null);
    }
  };

  const inferFileTypeFromName = (fileName?: string | null): string | null => {
    if (!fileName) return null;
    const lower = fileName.toLowerCase();
    if (lower.endsWith('.pdf')) return 'pdf';
    if (lower.endsWith('.docx')) return 'docx';
    return null;
  };

  const handleViewScanSummary = (scan: ATSScanHistoryItem) => {
    setResult({
      overall_score: scan.overall_score,
      breakdown: scan.breakdown,
      matched_keywords: scan.matched_keywords,
      missing_keywords: scan.missing_keywords,
      section_gaps: scan.section_gaps,
      recommendations: scan.recommendations,
    });

    setForm(prev => ({
      ...prev,
      resume_text: scan.resume_text_snapshot || prev.resume_text,
      job_description: scan.job_description_snapshot || prev.job_description,
      target_role: scan.target_role || '',
      industry: scan.industry || '',
    }));

    setErrors({});

    const derivedFileType = scan.resume_file_type || inferFileTypeFromName(scan.resume_file_name);
    if (scan.resume_id) {
      // CV still exists in library - load it for preview
      setSelectedResumeMeta({
        resumeId: scan.resume_id,
        fileName: scan.resume_file_name || '',
        fileType: derivedFileType || 'pdf',
      });
      setViewingDeletedCVSnapshot(false);
    } else {
      // CV was deleted - clear selection so form shows snapshot message instead of trying to load
      setSelectedResumeMeta(null);
      setViewingDeletedCVSnapshot(true);
    }

    window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  const formatScanDate = (value: string) => {
    const dt = new Date(value);
    if (Number.isNaN(dt.getTime())) return value;
    return dt.toLocaleString([], {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  const usageText: ReactNode = usageLoading ? (
    'Checking daily usage...'
  ) : usage ? (
    <>
      <span className="text-destructive">
        AI scans today: {usage.used_today}/{usage.daily_limit}
      </span>
      <span aria-hidden="true" className="text-muted-foreground">
        {' '}
        •{' '}
      </span>
      <span className="text-green-600">Remaining: {usage.remaining_today}</span>
    </>
  ) : (
    'AI usage unavailable right now'
  );

  return (
    <div className="space-y-6">
      <div className="grid gap-6 lg:grid-cols-2 items-start">
        <div className="space-y-4 lg:sticky lg:top-24 animate-fade-up">
        <h3 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">Result</h3>
        {loading ? (
          <AIScanAnimation />
        ) : result ? (
          <ATSResults result={result} />
        ) : (
          <ResultBlock label="ATS Results">
            <p className="text-sm text-muted-foreground leading-relaxed">
              Run ATS Check to view score breakdown, matched keywords, missing keywords, and recommendations here.
            </p>
          </ResultBlock>
        )}
        </div>

        <form onSubmit={handleSubmit} className="space-y-4 animate-slide-in-right rounded-2xl border border-border bg-card px-4 py-5 shadow-brand-sm">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">ATS Check</h3>
          <p className="text-xs text-muted-foreground">{usageText}</p>
        </div>
        <div className="grid sm:grid-cols-2 gap-4">
          <div>
            <Label htmlFor="ats-role">Target Role (optional)</Label>
            <Input
              id="ats-role"
              placeholder="e.g. Product Manager"
              value={form.target_role}
              onChange={set('target_role')}
              disabled={loading}
            />
          </div>
          <div>
            <Label htmlFor="ats-industry">Industry (optional)</Label>
            <Input
              id="ats-industry"
              placeholder="e.g. Banking, Technology"
              value={form.industry}
              onChange={set('industry')}
              disabled={loading}
            />
          </div>
        </div>

        <div>
          <Label>Resume *</Label>
          <div className="mt-2 mb-2">
            <ResumeLibrarySelector
              disabled={loading}
              onResumeLoaded={(selection) => {
                setForm(prev => ({ ...prev, resume_text: selection.resumeText }));
                setErrors(prev => ({ ...prev, resume_text: '' }));
                setSelectedResumeMeta({
                  resumeId: selection.resumeId,
                  fileName: selection.fileName,
                  fileType: selection.fileType,
                });
                setViewingDeletedCVSnapshot(false);
              }}
            />
          </div>

          {selectedResumeMeta ? (
            <ResumeDocumentViewer
              resumeId={selectedResumeMeta.resumeId}
              fileName={selectedResumeMeta.fileName}
              fileType={selectedResumeMeta.fileType}
            />
          ) : viewingDeletedCVSnapshot ? (
            <div className="rounded-md border border-amber-400 bg-amber-50 p-3">
              <p className="text-sm font-medium text-amber-900">CV No Longer Available</p>
              <p className="mt-1 text-xs text-amber-800">
                The original CV was deleted from your library. Showing snapshot of the resume text that was used during this scan.
              </p>
            </div>
          ) : (
            <p className="rounded-md border border-dashed border-border bg-background p-3 text-sm text-muted-foreground">
              Select or upload a resume to preview it here. Extracted text is used internally for ATS analysis and is not displayed.
            </p>
          )}

          {errors.resume_text && (
            <p className="mt-1 text-xs text-destructive">{errors.resume_text}</p>
          )}
        </div>

        <div>
          <Label htmlFor="ats-jd">Job Description *</Label>
          <Textarea
            id="ats-jd"
            placeholder="Paste the job description here…"
            value={form.job_description}
            onChange={set('job_description')}
            rows={5}
            disabled={loading}
            className="resize-none"
          />
          {errors.job_description && (
            <p className="mt-1 text-xs text-destructive">{errors.job_description}</p>
          )}
        </div>

        <Button type="submit" variant="brand" disabled={loading} className="w-full sm:w-auto">
          {loading ? (
            <>
              <span className="h-4 w-4 animate-spin rounded-full border-2 border-primary-foreground border-t-transparent" />
              Scanning with Gemini AI...
            </>
          ) : (
            'Run ATS Check'
          )}
        </Button>
        </form>
      </div>

      <section className="rounded-2xl border border-border bg-card p-5 shadow-brand-sm animate-fade-up space-y-3">
        <div className="flex items-center justify-between">
          <h3 className="text-base font-semibold text-foreground">Your Scans</h3>
          <span className="text-xs text-muted-foreground">{history.length} saved</span>
        </div>

        {historyLoading ? (
          <p className="text-sm text-muted-foreground">Loading scan history...</p>
        ) : history.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No scans yet. Run ATS Check to save your CV analysis history.
          </p>
        ) : (
          <ul className="space-y-2">
            {history.map(scan => (
              <li key={scan.scan_id} className="rounded-xl border border-border bg-background px-4 py-3">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0 space-y-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="rounded-full border border-border bg-card px-2 py-0.5 text-xs font-semibold text-foreground">
                        ATS {scan.overall_score}/100
                      </span>
                      <span className="text-xs text-muted-foreground">{formatScanDate(scan.created_at)}</span>
                      {!scan.resume_id && (
                        <span className="rounded-full border border-amber-400 bg-amber-50 px-2 py-0.5 text-xs font-medium text-amber-700">
                          CV Deleted
                        </span>
                      )}
                    </div>
                    <p className="text-sm text-foreground leading-relaxed">{scan.summary}</p>
                    <p className="text-xs text-muted-foreground">
                      CV: {scan.resume_file_name || 'Custom text'}
                      {!scan.resume_id && scan.resume_file_name && ' (deleted)'} • Matched: {scan.matched_keywords_count} • Missing: {scan.missing_keywords_count}
                    </p>
                  </div>

                  <div className="flex items-center gap-2">
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={() => handleViewScanSummary(scan)}
                      className="gap-1.5"
                    >
                      <Eye className="h-4 w-4" />
                      View Full Summary
                    </Button>
                    <Button
                      type="button"
                      variant="outline"
                      size="icon"
                      onClick={() => handleDeleteScan(scan.scan_id)}
                      disabled={deletingScanId === scan.scan_id}
                      aria-label="Delete scan history item"
                      className="text-muted-foreground hover:text-destructive hover:border-destructive"
                    >
                      <Trash2 />
                    </Button>
                  </div>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
