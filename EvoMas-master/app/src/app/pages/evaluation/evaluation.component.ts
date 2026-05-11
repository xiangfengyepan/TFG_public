import {
  Component, OnInit, OnDestroy, ViewChild,
  ElementRef, AfterViewChecked, ChangeDetectorRef,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Subscription } from 'rxjs';
import { ApiService } from '../../services/api.service';
import { EvaluationRunService, LogLine } from '../../services/evaluation-run.service';
import { PredictionInspection } from '../../models/types';
import { EvoButtonComponent, EvoSelectComponent, EvoSpinboxComponent, EvoBoxComponent } from '../../components/index';

@Component({
  selector: 'app-evaluation',
  standalone: true,
  imports: [CommonModule, FormsModule, EvoButtonComponent, EvoSelectComponent, EvoSpinboxComponent, EvoBoxComponent],
  templateUrl: './evaluation.component.html',
  styleUrl: './evaluation.component.css',
})
export class EvaluationComponent implements OnInit, OnDestroy, AfterViewChecked {
  @ViewChild('logEl') logEl!: ElementRef<HTMLDivElement>;

  // ─── Transient UI state (not persisted across navigation) ──────
  availablePredictions: string[] = [];
  /** Options for `evo-select`: label = filename, value = full path. */
  predictionOptions: { value: string; label: string }[] = [];
  /** Auto-detected (subset, split, instance_ids) groups for the picked
   * prediction, displayed in the "Subset / split / run ID" panel. */
  inspection: PredictionInspection | null = null;
  inspectionError = '';
  inspectionLoading = false;
  private shouldScroll = false;
  private changeSub?: Subscription;
  private lastInspectedPath = '';

  constructor(
    public evalSvc: EvaluationRunService,
    private api: ApiService,
    private cdr: ChangeDetectorRef,
  ) {}

  // ─── Getters delegating to service ─────────────────────────────
  get running(): boolean { return this.evalSvc.running; }
  get logs(): LogLine[] { return this.evalSvc.logs; }
  get progressPercent(): number { return this.evalSvc.progressPercent; }
  get progressDone(): number { return this.evalSvc.progressDone; }
  get progressTotal(): number { return this.evalSvc.progressTotal; }
  get stats() { return this.evalSvc.stats; }
  get errorMsg(): string { return this.evalSvc.errorMsg; }
  get returnCode(): number | null { return this.evalSvc.returnCode; }

  // The shared `evo-select` writes through this setter so we can refresh the
  // inspection panel whenever the picked file changes.
  get predictionsPath(): string { return this.evalSvc.predictionsPath; }
  set predictionsPath(v: string) {
    this.evalSvc.predictionsPath = v;
    this.refreshInspection();
  }

  ngOnInit(): void {
    this.loadPredictions();
    this.changeSub = this.evalSvc.changed.subscribe(() => {
      this.shouldScroll = true;
      this.cdr.markForCheck();
    });
  }

  refreshInspection(): void {
    const path = this.evalSvc.predictionsPath;
    if (!path) {
      this.inspection = null;
      this.inspectionError = '';
      this.lastInspectedPath = '';
      return;
    }
    if (path === this.lastInspectedPath) return;
    this.lastInspectedPath = path;
    this.inspectionLoading = true;
    this.inspectionError = '';
    this.cdr.markForCheck();
    this.api.inspectPrediction(path).subscribe({
      next: (res) => {
        this.inspection = res;
        this.inspectionLoading = false;
        this.cdr.markForCheck();
      },
      error: (err) => {
        this.inspection = null;
        this.inspectionError = err?.error?.detail ?? err?.message ?? 'Inspection failed';
        this.inspectionLoading = false;
        this.cdr.markForCheck();
      },
    });
  }

  ngOnDestroy(): void {
    this.changeSub?.unsubscribe();
    // Do NOT cancel evalSvc — evaluation keeps running across navigation
  }

  ngAfterViewChecked(): void {
    if (this.shouldScroll && this.logEl) {
      const el = this.logEl.nativeElement;
      el.scrollTop = el.scrollHeight;
      this.shouldScroll = false;
    }
  }

  loadPredictions(): void {
    this.api.getPredictions().subscribe(paths => {
      this.availablePredictions = paths;
      this.predictionOptions = paths.map(p => ({ value: p, label: this.fileName(p) }));
      if (!this.evalSvc.predictionsPath && paths.length > 0)
        this.evalSvc.predictionsPath = paths[0];
      this.refreshInspection();
      this.cdr.markForCheck();
    });
  }

  run(): void { this.evalSvc.run(); }
  cancel(): void { this.evalSvc.cancel(); }
  clearLogs(): void { this.evalSvc.clearLogs(); }

  fileName(path: string): string {
    return path.split(/[/\\]/).pop() ?? path;
  }

  /** Last error from the file-picker flow — surfaced under the predictions
   * row when the picked file isn't in results/predictions/. */
  filePickerError = '';

  /** OS file-picker handler. Browsers don't expose absolute paths, so we
   * resolve the chosen file against the server's listing of
   * results/predictions/ (already populated by `loadPredictions`) and pre-
   * select the matching entry. Files outside that folder can't be used by
   * the harness — the user is told to copy/move them in first. */
  onPredictionFileChosen(event: Event): void {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    input.value = '';
    if (!file) return;
    this.filePickerError = '';

    const resolveFromList = () => {
      const match = this.availablePredictions.find(p => this.fileName(p) === file.name);
      if (match) {
        this.predictionsPath = match;
        this.cdr.markForCheck();
        return true;
      }
      return false;
    };

    if (resolveFromList()) return;
    // Not in the cached listing — refresh once in case it was just added.
    this.api.getPredictions().subscribe({
      next: paths => {
        this.availablePredictions = paths;
        this.predictionOptions = paths.map(p => ({ value: p, label: this.fileName(p) }));
        if (!resolveFromList()) {
          this.filePickerError =
            `"${file.name}" isn't under results/predictions/. ` +
            `Move/copy it there and try again — the harness only reads files under that folder.`;
        }
        this.cdr.markForCheck();
      },
      error: () => {
        this.filePickerError = `"${file.name}" isn't under results/predictions/.`;
        this.cdr.markForCheck();
      },
    });
  }
}
