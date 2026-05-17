import { Component, ElementRef, HostListener, ViewChild, ChangeDetectorRef, OnInit, OnDestroy } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RouterOutlet, RouterLink, RouterLinkActive } from '@angular/router';
import { ApiService } from './services/api.service';
import { TopologyStateService } from './services/topology-state.service';
import { UnifiedConfig } from './models/types';
import { ApragonIconComponent } from './components/index';

@Component({
  selector: 'app-root',
  imports: [CommonModule, FormsModule, RouterOutlet, RouterLink, RouterLinkActive, ApragonIconComponent],
  templateUrl: './app.html',
  styleUrl: './app.css',
})
export class App implements OnInit, OnDestroy {
  @ViewChild('fileInput') fileInput!: ElementRef<HTMLInputElement>;

  menuOpen = false;
  saveDialogOpen = false;
  saveName = '';
  saveError = '';

  apiOnline: boolean | null = null;
  apiHost = '';
  private healthTimer?: ReturnType<typeof setInterval>;
  /** True after at least one failed probe; used to detect "API came back" so
   * we can hard-reload and pick up any backend changes. */
  private wasOffline = false;

  constructor(
    private api: ApiService,
    private state: TopologyStateService,
    private cdr: ChangeDetectorRef,
  ) {}

  ngOnInit(): void {
    this.apiHost = this.api.apiHost;
    this.checkHealth();
    this.healthTimer = setInterval(() => this.checkHealth(), 5000);
  }

  ngOnDestroy(): void {
    if (this.healthTimer) clearInterval(this.healthTimer);
  }

  private checkHealth(): void {
    this.api.getHealth().subscribe({
      next: () => {
        if (this.wasOffline) {
          // API was down and is now back. Hard-reload so we pick up any backend
          // changes (uvicorn --reload, schema migrations, restarted processes,
          // …) without leaving the UI sitting on stale data.
          window.location.reload();
          return;
        }
        if (this.apiOnline !== true) {
          this.apiOnline = true;
          this.cdr.markForCheck();
        }
      },
      error: () => {
        this.wasOffline = true;
        if (this.apiOnline !== false) {
          this.apiOnline = false;
          this.cdr.markForCheck();
        }
      },
    });
  }

  toggleMenu(): void {
    this.menuOpen = !this.menuOpen;
  }

  @HostListener('document:click', ['$event'])
  onDocClick(ev: MouseEvent): void {
    if (!this.menuOpen) return;
    const target = ev.target as HTMLElement;
    if (target.closest('.brand-menu') || target.closest('.brand-trigger')) return;
    this.menuOpen = false;
  }

  openSaveDialog(): void {
    if (!this.state.currentConfig) {
      alert('No configuration loaded to save.');
      return;
    }
    this.saveName = this.state.currentConfigName ?? '';
    this.saveError = '';
    this.saveDialogOpen = true;
    this.menuOpen = false;
  }

  cancelSave(): void {
    this.saveDialogOpen = false;
    this.saveName = '';
    this.saveError = '';
  }

  confirmSave(): void {
    const name = this.saveName.trim();
    if (!name) { this.saveError = 'Name cannot be empty.'; return; }
    if (/[\\/:*?"<>|]/.test(name)) { this.saveError = 'Name contains invalid characters.'; return; }
    if (this.state.predefinedConfigs.some(c => c.stem === name || c.id === name)) {
      this.saveError = `"${name}" collides with a predefined config. Pick a different name.`;
      return;
    }
    if (!this.state.currentConfig) {
      this.saveError = 'No configuration loaded.';
      return;
    }

    // Sync the exported JSON's `id` to the chosen filename so the file
    // round-trips cleanly through Load config… (which validates that
    // id == filename stem). Clone first so the in-memory config the user
    // is editing isn't renamed under their feet.
    const cloned = { ...this.state.currentConfig, id: name } as UnifiedConfig;
    const json = JSON.stringify(cloned, null, 2);
    const blob = new Blob([json], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${name}.json`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);

    this.saveDialogOpen = false;
    this.saveName = '';
    this.saveError = '';
  }

  openFilePicker(): void {
    this.menuOpen = false;
    this.fileInput?.nativeElement.click();
  }

  onFileChosen(event: Event): void {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    input.value = '';
    if (!file) return;

    const reader = new FileReader();
    reader.onload = () => {
      let parsed: Record<string, unknown>;
      try {
        parsed = JSON.parse(reader.result as string) as Record<string, unknown>;
      } catch (err) {
        alert(`Failed to parse JSON: ${(err as Error).message}`);
        return;
      }
      const stem = file.name.replace(/\.json$/i, '');
      const reason = this.validateLoadedConfig(parsed, stem);
      if (reason) {
        alert(`Invalid config: ${reason}`);
        return;
      }
      this.persistLoadedConfig(stem, parsed);
    };
    reader.onerror = () => alert('Could not read file.');
    reader.readAsText(file);
  }

  /** Validate a JSON object as a config that can be loaded. The four required
   * top-level keys must exist (their values may be empty: `""`, `[]`, `{}`,
   * `null`) and the JSON's `id` must equal the filename stem.
   *
   * Returns a human-readable reason on failure, or null when valid. */
  private validateLoadedConfig(obj: Record<string, unknown>, stem: string): string | null {
    const required = ['id', 'entry', 'edges', 'agents'];
    const missing = required.filter(k => !(k in obj));
    if (missing.length) return `missing required key(s): ${missing.join(', ')}`;
    if (obj['id'] !== stem) {
      return `the JSON's "id" must match the filename. Got id=${JSON.stringify(obj['id'])}, file=${JSON.stringify(stem)}.`;
    }
    return null;
  }

  /** POST the loaded config to the backend. Handles the same-id collision
   * case by re-asking the user to confirm replacement, then retrying with
   * `replace=true`. On success, drops the in-memory current config so the
   * Topology page reflects the freshly-saved file via its config list. */
  private persistLoadedConfig(stem: string, data: Record<string, unknown>, replace = false): void {
    this.api.saveLoadedConfig(stem, data, replace).subscribe({
      next: () => this.refreshConfigsAfterImport(stem, data as unknown as UnifiedConfig),
      error: err => {
        if (err?.status === 409 && !replace) {
          if (confirm(
            `A loaded config named "${stem}" already exists.\n\nReplace it?`
          )) {
            this.persistLoadedConfig(stem, data, true);
          }
          return;
        }
        alert(`Failed to load config: ${err?.error?.detail ?? err?.message ?? 'unknown error'}`);
      },
    });
  }

  private refreshConfigsAfterImport(stem: string, data: UnifiedConfig): void {
    // Re-pull the config list so the Topology page's left panel shows the
    // newly-saved entry under "Loaded".
    this.api.getConfigs().subscribe({
      next: list => {
        this.state.predefinedConfigs = list;
        this.state.setCurrentConfig(data, stem);
        this.cdr.markForCheck();
      },
      error: () => { this.state.setCurrentConfig(data, stem); this.cdr.markForCheck(); },
    });
  }
}
