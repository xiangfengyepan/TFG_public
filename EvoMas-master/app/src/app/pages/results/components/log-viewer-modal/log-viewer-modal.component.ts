/** Full-screen modal that mounts the shared `<app-inference-instance-view>`
 * with a RunInstance snapshot parsed from a prediction's NDJSON event log.
 * Controlled component: parent owns load/parse and passes the instance in. */
import { Component, EventEmitter, HostListener, Input, Output } from '@angular/core';
import { CommonModule } from '@angular/common';
import { InferenceInstanceViewComponent } from '../../../../components/index';
import { RunInstance } from '../../../../services/inference-run.service';

@Component({
  selector: 'app-log-viewer-modal',
  standalone: true,
  imports: [CommonModule, InferenceInstanceViewComponent],
  templateUrl: './log-viewer-modal.component.html',
})
export class LogViewerModalComponent {
  @Input() open = false;
  @Input() loading = false;
  @Input() error = '';
  @Input() title = '';
  @Input() instance: RunInstance | null = null;

  @Output() close = new EventEmitter<void>();

  @HostListener('document:keydown.escape')
  onEsc(): void { if (this.open) this.close.emit(); }
}
