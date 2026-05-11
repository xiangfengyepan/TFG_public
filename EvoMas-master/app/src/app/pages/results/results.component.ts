import { Component, ChangeDetectorRef, ElementRef, OnInit, ViewChild } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ApiService } from '../../services/api.service';
import { ResultsStateService } from '../../services/results-state.service';
import { LogLine, parseLogLine } from '../../services/evaluation-run.service';
import {
  ResultInstance, ResultPrediction, ResultEvaluation,
  ResultPredictionFile, ResultEvaluationDir, ResultRun,
} from '../../models/types';
import { EvoBoxComponent, EvoButtonComponent, EvoSelectComponent, EvoSwitchComponent } from '../../components/index';

type LogName = 'run_instance.log' | 'test_output.txt' | 'eval.sh' | 'patch.diff' | 'report.json';

@Component({
  selector: 'app-results',
  standalone: true,
  imports: [CommonModule, FormsModule, EvoBoxComponent, EvoButtonComponent, EvoSelectComponent, EvoSwitchComponent],
  templateUrl: './results.component.html',
  styleUrl: './results.component.css',
})
export class ResultsComponent implements OnInit {
  @ViewChild('instanceList') instanceListEl?: ElementRef<HTMLDivElement>;

  instances: ResultInstance[] = [];

  // ─── Selection state (persisted across navigation) ─────────────
  get selectedId(): string | null { return this.state.selectedId; }
  set selectedId(v: string | null) { this.state.selectedId = v; }
  get selectedRunId(): string | null { return this.state.selectedRunId; }
  set selectedRunId(v: string | null) { this.state.selectedRunId = v; }

  // ─── Loaded artefacts (re-fetched on demand) ──────────────────
  prediction: ResultPrediction | null = null;
  evaluation: ResultEvaluation | null = null;
  /** NDJSON SSE-event transcript for `prediction`. `null` while loading,
   * empty string when the run was generated before the log writer landed. */
  predictionLog: string | null = null;
  predictionLogMissing = false;
  showPredictionLog = false;

  /** Convenience accessors so the template doesn't have to look up the run twice. */
  get selectedRun(): ResultRun | null {
    return this.current?.runs.find(r => r.run_id === this.selectedRunId) ?? null;
  }

  /** Options for the shared `evo-select`: value = run_id, label = run_id +
   * timestamp + a short pair-status descriptor. */
  get runOptions(): { value: string; label: string }[] {
    const runs = this.current?.runs ?? [];
    return runs.map(r => {
      const ts = this.formatTs(r.mtime);
      const tag = (r.prediction && r.evaluation) ? 'pred + eval'
                : (r.prediction)                  ? 'pred only — no eval yet'
                :                                   'eval only — prediction missing';
      return { value: r.run_id, label: `${r.run_id} — ${ts} · ${tag}` };
    });
  }
  get selectedPredFile(): ResultPredictionFile | null {
    return this.selectedRun?.prediction ?? null;
  }
  get selectedEvalDir(): ResultEvaluationDir | null {
    return this.selectedRun?.evaluation ?? null;
  }

  /** Start of this instance's inference, parsed from the first timestamped
   * line of the prediction's .log file (the user-facing Python `logging`
   * transcript at `results/predictions/logs/<stem>.log`). The first line
   * always logs at the moment the worker starts processing, so it's the
   * authoritative start time even when the file's mtime drifts due to
   * other instances finishing later in the same run.
   *
   * Falls back to the prediction line's `started_at` field, then to a dash
   * for legacy runs that have neither. */
  get predictionTimestamp(): string {
    const fromLog = this.firstLogTimestamp(this.predictionLog ?? '');
    if (fromLog) return fromLog.toLocaleString();
    const startedAt = this.prediction?.data?.['started_at'];
    if (typeof startedAt === 'number') return new Date(startedAt).toLocaleString();
    return '—';
  }

  /** Scan the head of the .log content for the first line matching the
   * Python `logging` default format (`YYYY-MM-DD HH:MM:SS,mmm - LEVEL …`).
   * Returns the parsed Date, or null when none of the first ~20 lines do.
   * Limiting the scan keeps a malformed log from costing more than a few
   * regex tests per render. */
  private firstLogTimestamp(raw: string): Date | null {
    if (!raw) return null;
    const re = /^(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2})[,.](\d{1,6})/;
    const lines = raw.split('\n', 25);
    for (const line of lines) {
      const m = re.exec(line);
      if (!m) continue;
      // Build an ISO-ish string the JS Date constructor reliably parses.
      const ms = m[3].padEnd(3, '0').slice(0, 3);
      const d = new Date(`${m[1]}T${m[2]}.${ms}`);
      if (!Number.isNaN(d.getTime())) return d;
    }
    return null;
  }

  /** End of this instance's inference (epoch ms, recorded the moment the
   * prediction line is written to disk). Falls back to the file's mtime
   * for legacy predictions — that is genuinely close to "ended at". */
  get predictionEndTimestamp(): string {
    const endedAt = this.prediction?.data?.['ended_at'];
    if (typeof endedAt === 'number') return new Date(endedAt).toLocaleString();
    const p = this.selectedPredFile;
    return p ? new Date(p.mtime * 1000).toLocaleString() : '—';
  }

  /** Wall-clock duration of this instance's inference, formatted as
   * `HH:MM:SS` (or `MM:SS` under an hour). Empty when timing is missing.
   * Uses the .log's first-line timestamp for the start (matching what the
   * "Start of inference" row shows) and the prediction line's `ended_at`
   * (or file mtime) for the end. */
  get predictionDuration(): string {
    const startDate = this.firstLogTimestamp(this.predictionLog ?? '');
    const startMs = startDate
      ? startDate.getTime()
      : (typeof this.prediction?.data?.['started_at'] === 'number'
          ? (this.prediction!.data!['started_at'] as number)
          : NaN);
    const endRaw = this.prediction?.data?.['ended_at'];
    const endMs = typeof endRaw === 'number'
      ? endRaw
      : (this.selectedPredFile ? this.selectedPredFile.mtime * 1000 : NaN);
    if (!Number.isFinite(startMs) || !Number.isFinite(endMs) || endMs < startMs) return '';
    const total = Math.round((endMs - startMs) / 1000);
    const h = Math.floor(total / 3600);
    const m = Math.floor((total % 3600) / 60);
    const s = total % 60;
    const pad = (n: number) => n.toString().padStart(2, '0');
    return h > 0 ? `${h}:${pad(m)}:${pad(s)}` : `${pad(m)}:${pad(s)}`;
  }

  /** The config name used to produce this run, derived from the run_id
   * (worker writes it as `<config_name>-<UID>`). Falls back to the raw
   * run_id when the format doesn't match. */
  get predictionConfigUsed(): string {
    const runId = this.selectedRunId ?? '';
    if (!runId) return '—';
    const m = runId.match(/^(.+)-[0-9a-f]{6,}$/);
    return m ? m[1] : runId;
  }

  get showLogs(): boolean { return this.state.showLogs; }
  set showLogs(v: boolean) { this.state.showLogs = v; }
  get activeLog(): LogName { return this.state.activeLog; }
  set activeLog(v: LogName) { this.state.activeLog = v; }
  get filter(): string { return this.state.filter; }
  set filter(v: string) { this.state.filter = v; }
  get groupByInstance(): boolean { return this.state.groupByInstance; }
  set groupByInstance(v: boolean) { this.state.groupByInstance = v; }

  /** Instances visible after applying `filter`. The filter matches instance_id
   * substrings OR the run_id of any prediction/evaluation belonging to the
   * instance, so users can search by either the SWE-bench id or a specific
   * prediction-evaluation set. */
  get filteredInstances(): ResultInstance[] {
    const q = this.filter.trim().toLowerCase();
    if (!q) return this.instances;
    return this.instances.filter(inst =>
      inst.instance_id.toLowerCase().includes(q) ||
      inst.runs.some(r => (r.run_id || '').toLowerCase().includes(q))
    );
  }

  /** Group filtered instances by job (run_id). Every instance belongs to one
   * or more runs (a single inference push may have produced predictions for
   * several instance ids, which all share the same run_id), so iterating
   * `(instance, run)` pairs and bucketing by run_id rebuilds the original
   * inference jobs from the per-instance result tree. The most recent job
   * comes first; clicking an instance row inside a job auto-pins the right
   * panel to that exact (instance, run) pair. */
  get jobGroups(): { runId: string; mtime: number; entries: { instance: ResultInstance; run: ResultRun }[] }[] {
    const map = new Map<string, { runId: string; mtime: number; entries: { instance: ResultInstance; run: ResultRun }[] }>();
    for (const inst of this.filteredInstances) {
      for (const run of inst.runs) {
        const key = run.run_id || '(unknown)';
        let g = map.get(key);
        if (!g) { g = { runId: key, mtime: 0, entries: [] }; map.set(key, g); }
        g.entries.push({ instance: inst, run });
        if (run.mtime > g.mtime) g.mtime = run.mtime;
      }
    }
    return [...map.values()].sort((a, b) => b.mtime - a.mtime);
  }

  isJobOpen(runId: string): boolean { return this.state.isSubsetOpen(`job/${runId}`); }
  toggleJob(runId: string): void { this.state.toggleSubset(`job/${runId}`); }

  selectInstanceInJob(instance: ResultInstance, run: ResultRun): void {
    const idChanged = this.selectedId !== instance.instance_id;
    if (idChanged) {
      this.selectedId = instance.instance_id;
      this.prediction = null;
      this.evaluation = null;
      this.predictionLog = null;
      this.predictionLogMissing = false;
      this.showPredictionLog = false;
      this.logContent = '';
      this.showLogs = false;
    }
    this.selectRun(run.run_id ?? null);
  }
  logContent = '';
  loadingLog = false;

  loading = false;
  error = '';

  constructor(
    private api: ApiService,
    private state: ResultsStateService,
    private cdr: ChangeDetectorRef,
  ) {}

  ngOnInit(): void {
    this.refresh();
  }

  /** After `refresh()` repopulates `instances`, restore the loaded artefacts
   * for the run the user last had open (if it still exists). */
  private restoreSelection(): void {
    if (!this.selectedRunId) return;
    const run = this.selectedRun;
    if (!run) return;
    if (run.prediction) this.loadPrediction(run.prediction);
    if (run.evaluation) this.loadEvaluation(run.evaluation);
  }

  refresh(): void {
    this.loading = true;
    this.error = '';
    this.api.getResultInstances().subscribe({
      next: (list) => {
        this.instances = list;
        if (this.selectedId && !list.find(i => i.instance_id === this.selectedId)) {
          this.clearSelection();
        } else {
          // Re-load artefacts for the previously selected run, if any.
          this.restoreSelection();
        }
        this.loading = false;
        this.cdr.markForCheck();
      },
      error: (err) => {
        this.error = `Failed to load results: ${err.message ?? err}`;
        this.loading = false;
        this.cdr.markForCheck();
      },
    });
  }

  get current(): ResultInstance | null {
    return this.instances.find(i => i.instance_id === this.selectedId) ?? null;
  }

  selectInstance(id: string): void {
    if (this.selectedId === id) return;
    this.selectedId = id;
    this.prediction = null;
    this.evaluation = null;
    this.predictionLog = null;
    this.predictionLogMissing = false;
    this.showPredictionLog = false;
    this.logContent = '';
    this.showLogs = false;
    // Auto-pick the most recent run (the runs[] list is mtime-desc on the server).
    const firstRun = this.current?.runs[0] ?? null;
    this.selectRun(firstRun?.run_id ?? null);
  }

  clearSelection(): void {
    this.selectedId = null;
    this.selectedRunId = null;
    this.prediction = null;
    this.evaluation = null;
    this.predictionLog = null;
    this.predictionLogMissing = false;
    this.logContent = '';
  }

  selectRun(runId: string | null): void {
    this.selectedRunId = runId;
    this.prediction = null;
    this.evaluation = null;
    this.predictionLog = null;
    this.predictionLogMissing = false;
    this.predictionConfigJson = '';
    this.predictionConfigPath = '';
    this.logContent = '';
    if (this.selectedPredFile) {
      this.loadPrediction(this.selectedPredFile);
      this.loadPredictionLog(this.selectedPredFile);
      this.loadPredictionConfig(this.selectedPredFile);
    }
    if (this.selectedEvalDir)  this.loadEvaluation(this.selectedEvalDir);
    this.revealActiveInLeftPanel();
    this.cdr.markForCheck();
  }

  /** When the user picks a run from the dropdown, reveal it on the left
   * panel: expand the matching job group (if grouping by job) and scroll
   * the entry into view. Called from selectRun. */
  private revealActiveInLeftPanel(): void {
    const id = this.selectedId;
    const runId = this.selectedRunId;
    if (!id) return;
    if (!this.groupByInstance && runId) {
      // Auto-expand the job group containing this run (job grouping is
      // the default left-panel layout).
      if (!this.isJobOpen(runId)) this.toggleJob(runId);
    }
    // Defer the scroll until Angular renders the (possibly newly-expanded)
    // group so the target element exists in the DOM.
    setTimeout(() => {
      const root = this.instanceListEl?.nativeElement;
      if (!root) return;
      // Match the active row first; in flat mode that's enough, in grouped
      // mode the .active class lands on the (instance × run) row.
      const target = root.querySelector('.inst-item.active') as HTMLElement | null;
      if (target) target.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }, 0);
  }

  // ─── Per-run config snapshot ──────────────────────────────────
  predictionConfigJson = '';
  predictionConfigPath = '';

  private loadPredictionConfig(p: ResultPredictionFile): void {
    this.api.getResultPredictionConfig(p.path).subscribe({
      next: res => {
        this.predictionConfigJson = res.exists ? res.raw : '';
        this.predictionConfigPath = res.exists ? res.path : '';
        this.cdr.markForCheck();
      },
      error: () => { this.predictionConfigJson = ''; this.predictionConfigPath = ''; this.cdr.markForCheck(); },
    });
  }

  /** Download the snapshot of the unified-config JSON used to produce this
   * run. The worker writes it to results/predictions/configs/<stem>.json
   * so renames/deletes of the source config don't strand previous runs. */
  downloadPredictionConfig(): void {
    if (!this.prediction || !this.predictionConfigJson) return;
    const stem = this.prediction.name.replace(/^prediction-/, '').replace(/\.jsonl$/i, '');
    this.downloadText(this.predictionConfigJson, `${stem}.json`, 'application/json');
  }

  togglePredictionLog(on: boolean): void {
    this.showPredictionLog = on;
  }

  private loadPredictionLog(p: ResultPredictionFile): void {
    this.api.getResultPredictionLog(p.path).subscribe({
      next: (res) => {
        this.predictionLog = res.raw;
        this.predictionLogMissing = !res.exists;
        this.predictionLogPath = res.exists ? res.path : null;
        this.cdr.markForCheck();
      },
      error: () => {
        this.predictionLog = '';
        this.predictionLogMissing = true;
        this.predictionLogPath = null;
        this.cdr.markForCheck();
      },
    });
  }

  private loadPrediction(p: ResultPredictionFile): void {
    this.api.getResultPrediction(p.path, this.selectedId ?? undefined).subscribe({
      next: (res) => { this.prediction = res; this.cdr.markForCheck(); },
      error: (err) => { this.error = `Prediction load failed: ${err.message ?? err}`; this.cdr.markForCheck(); },
    });
  }

  private loadEvaluation(e: ResultEvaluationDir): void {
    this.api.getResultEvaluation(e.dir).subscribe({
      next: (res) => {
        this.evaluation = res;
        this.cdr.markForCheck();
        if (this.showLogs) this.fetchLog();
      },
      error: (err) => { this.error = `Evaluation load failed: ${err.message ?? err}`; this.cdr.markForCheck(); },
    });
  }

  toggleLogs(on: boolean): void {
    this.showLogs = on;
    if (on && !this.logContent) this.fetchLog();
  }

  setActiveLog(name: LogName): void {
    if (this.activeLog === name) return;
    this.activeLog = name;
    this.fetchLog();
  }

  private fetchLog(): void {
    if (!this.selectedEvalDir) return;
    this.loadingLog = true;
    this.logContent = '';
    this.api.getResultEvaluationLog(this.selectedEvalDir.dir, this.activeLog).subscribe({
      next: (res) => { this.logContent = res.content; this.loadingLog = false; this.cdr.markForCheck(); },
      error: (err) => {
        this.logContent = `(failed to load log: ${err?.error?.detail ?? err?.message ?? err})`;
        this.loadingLog = false;
        this.cdr.markForCheck();
      },
    });
  }

  // ─── Downloads ─────────────────────────────────────────────
  downloadPrediction(): void {
    if (!this.prediction) return;
    this.downloadText(this.prediction.raw, this.prediction.name, 'application/jsonl');
  }

  downloadPredictionLogFile(): void {
    if (!this.prediction || !this.predictionLog) return;
    // Mirror the prediction filename's stem (`prediction-<run_id>`) so the
    // .log sidecar is paired with the .jsonl in the user's Downloads folder.
    const stem = this.prediction.name.replace(/\.jsonl$/i, '');
    this.downloadText(this.predictionLog, `${stem}.log`, 'application/x-ndjson');
  }

  /** Open the OS file explorer with the given path highlighted. Errors are
   * silent — there's no user-visible recovery if the OS rejects the call. */
  reveal(path: string | null | undefined): void {
    if (!path) return;
    this.api.revealInExplorer(path).subscribe({ error: () => { /* swallow */ } });
  }

  predictionLogPath: string | null = null;

  downloadZip(): void {
    if (!this.selectedEvalDir) return;
    const url = this.api.getResultEvaluationZipUrl(this.selectedEvalDir.dir);
    const a = document.createElement('a');
    a.href = url;
    a.rel = 'noopener';
    document.body.appendChild(a); a.click(); document.body.removeChild(a);
  }

  downloadLog(): void {
    if (!this.logContent) return;
    const id = this.selectedId ?? 'log';
    this.downloadText(this.logContent, `${id}.${this.activeLog}`, 'text/plain');
  }

  private downloadText(text: string, filename: string, mime: string): void {
    const blob = new Blob([text], { type: mime });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = filename;
    document.body.appendChild(a); a.click(); document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  // ─── View helpers ──────────────────────────────────────────
  formatTs(mtime: number): string {
    return new Date(mtime * 1000).toLocaleString();
  }

  formatDiff(patch: string): { line: string; cls: string }[] {
    return (patch || '').split('\n').map(line => {
      let cls = '';
      if (line.startsWith('+') && !line.startsWith('+++')) cls = 'diff-add';
      else if (line.startsWith('-') && !line.startsWith('---')) cls = 'diff-rm';
      else if (line.startsWith('@@') || line.startsWith('diff ')) cls = 'diff-hdr';
      return { line, cls };
    });
  }

  /** Lazily-built, format-aware colored render of `logContent`.
   * Each tab gets a renderer tuned to its file shape:
   *   - run_instance.log → Python log levels (parseLogLine, same as Evaluation page)
   *   - test_output.txt  → pytest PASSED/FAILED/ERROR/skipped highlighting
   *   - eval.sh          → shell comments greyed, shebangs marked
   *   - patch.diff       → standard diff coloring (added/removed/header)
   *   - report.json      → pretty-printed JSON
   */
  coloredLog(): LogLine[] {
    if (!this.logContent) return [];
    const lines = this.logContent.split('\n');
    switch (this.activeLog) {
      case 'test_output.txt': return lines.map(this.parseTestLine);
      case 'eval.sh':         return lines.map(this.parseShellLine);
      case 'patch.diff':      return lines.map(this.parseDiffLine);
      case 'report.json':     return this.parseJsonLines();
      case 'run_instance.log':
      default:                return lines.map(parseLogLine);
    }
  }

  // ─── Per-format colorizers (each returns a LogLine = LogSegment[]) ─────
  private parseTestLine(line: string): LogLine {
    if (!line.trim()) return [{ t: line || ' ', c: 'sl-dim' }];
    // PASSED / FAILED / ERROR / SKIPPED keywords (pytest output).
    const kw = line.match(/\b(PASSED|FAILED|ERROR|SKIPPED|XFAIL|XPASS)\b/);
    if (kw) {
      const idx = kw.index!;
      const cls =
        kw[1] === 'PASSED' || kw[1] === 'XPASS' ? 'sl-ok' :
        kw[1] === 'SKIPPED' || kw[1] === 'XFAIL' ? 'sl-warn-msg' : 'sl-err-msg';
      return [
        { t: line.slice(0, idx), c: 'sl-text' },
        { t: kw[1], c: cls },
        { t: line.slice(idx + kw[1].length), c: 'sl-text' },
      ];
    }
    if (/^=+\s.*\s=+$/.test(line)) return [{ t: line, c: 'sl-info' }];   // ===== summary =====
    if (/^_{3,}\s/.test(line))      return [{ t: line, c: 'sl-warn' }];   // ___ test name ___
    if (/^(Traceback|.*Error:|.*Exception:|\s+File ")/.test(line)) {
      return [{ t: line, c: 'sl-err-msg' }];
    }
    if (/^collected \d+ item/.test(line)) return [{ t: line, c: 'sl-info' }];
    return [{ t: line, c: 'sl-text' }];
  }

  private parseShellLine(line: string): LogLine {
    if (line.startsWith('#!')) return [{ t: line, c: 'sl-info' }];
    if (line.trimStart().startsWith('#')) return [{ t: line, c: 'sl-dim' }];
    return [{ t: line || ' ', c: 'sl-text' }];
  }

  private parseDiffLine(line: string): LogLine {
    if (line.startsWith('+') && !line.startsWith('+++')) return [{ t: line, c: 'diff-add' }];
    if (line.startsWith('-') && !line.startsWith('---')) return [{ t: line, c: 'diff-rm' }];
    if (line.startsWith('@@') || line.startsWith('diff ')
        || line.startsWith('+++') || line.startsWith('---'))
      return [{ t: line, c: 'diff-hdr' }];
    return [{ t: line, c: 'sl-text' }];
  }

  /** Pretty-print + light coloring for report.json. */
  private parseJsonLines(): LogLine[] {
    let pretty = this.logContent;
    try { pretty = JSON.stringify(JSON.parse(this.logContent), null, 2); } catch { /* fall through */ }
    return pretty.split('\n').map(line => {
      // String values (very loose tokenization — good enough for one-line keys/values).
      const out: LogLine = [];
      const re = /("(?:\\.|[^"\\])*")|(\b(?:true|false|null)\b)|(-?\d+(?:\.\d+)?)/g;
      let last = 0;
      let m: RegExpExecArray | null;
      while ((m = re.exec(line)) !== null) {
        if (m.index > last) out.push({ t: line.slice(last, m.index), c: 'sl-text' });
        const cls = m[1] ? 'sl-ok'        // strings
                  : m[2] ? 'sl-warn'      // booleans / null
                  :        'sl-info';     // numbers
        out.push({ t: m[0], c: cls });
        last = m.index + m[0].length;
      }
      if (last < line.length) out.push({ t: line.slice(last), c: 'sl-text' });
      return out.length ? out : [{ t: line || ' ', c: 'sl-dim' }];
    });
  }

  resolvedFlag(): boolean | null {
    const r = this.evaluation?.report;
    if (!r) return null;
    const inner = r[this.selectedId ?? ''] as Record<string, unknown> | undefined;
    if (inner && typeof inner['resolved'] === 'boolean') return inner['resolved'] as boolean;
    return null;
  }

  testStatus(): { passed: number; failed: number; group: string }[] | null {
    const inner = this.evaluation?.report?.[this.selectedId ?? ''] as Record<string, unknown> | undefined;
    const status = inner?.['tests_status'] as Record<string, { success?: string[]; failure?: string[] }> | undefined;
    if (!status) return null;
    return Object.entries(status).map(([group, g]) => ({
      group,
      passed: g.success?.length ?? 0,
      failed: g.failure?.length ?? 0,
    }));
  }
}
