import { Component, ElementRef, HostListener, ViewChild, ChangeDetectorRef, OnInit, OnDestroy } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RouterOutlet, RouterLink, RouterLinkActive } from '@angular/router';
import { ApiService } from './services/api.service';
import { TopologyStateService } from './services/topology-state.service';
import { UnifiedConfig, ConfigSummary } from './models/types';
import { ApragonIconComponent, EvoSelectComponent } from './components/index';
import type { SelectOption, SelectOptionGroup } from './components/select/evo-select.component';

@Component({
  selector: 'app-root',
  imports: [CommonModule, FormsModule, RouterOutlet, RouterLink, RouterLinkActive, ApragonIconComponent, EvoSelectComponent],
  templateUrl: './app.html',
  styleUrl: './app.css',
})
export class App implements OnInit, OnDestroy {
  @ViewChild('fileInput') fileInput!: ElementRef<HTMLInputElement>;

  menuOpen = false;
  saveDialogOpen = false;
  saveName = '';
  saveError = '';

  // "Create from template" dialog — predefined + loaded both eligible.
  templateDialogOpen = false;
  templateOptions: ConfigSummary[] = [];
  templateChoice = '';
  templateNewName = '';
  templateError = '';
  templateBusy = false;

  /** `templateOptions` shaped for `<evo-select [optgroups]>` — Predefined then Loaded. */
  get templateSelectGroups(): SelectOptionGroup[] {
    const groups: SelectOptionGroup[] = [];
    const predefined = this.templateOptions.filter(c => c.source === 'predefined');
    const loaded = this.templateOptions.filter(c => c.source === 'loaded');
    if (predefined.length > 0) {
      groups.push({
        label: 'Predefined',
        items: predefined.map(t => ({ value: t.stem, label: t.id || t.stem })),
      });
    }
    if (loaded.length > 0) {
      groups.push({
        label: 'Loaded',
        items: loaded.map(t => ({ value: t.stem, label: t.id || t.stem })),
      });
    }
    return groups;
  }

  apiOnline: boolean | null = null;
  apiHost = '';
  private healthTimer?: ReturnType<typeof setInterval>;
  /** True after at least one failed probe — triggers a hard-reload on recovery. */
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
          // API recovered — reload to pick up any backend changes.
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

    // Sync `id` to the chosen filename — loader enforces id == stem.
    // Clone first so the editing session isn't mutated.
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

  /** Open the "Create from template" modal. Snapshots the config list
   * to avoid mid-flight reactivity. */
  openCreateFromTemplate(): void {
    this.templateOptions = this.state.predefinedConfigs.slice();
    if (this.templateOptions.length === 0) {
      alert('No templates available.');
      this.menuOpen = false;
      return;
    }
    // Default to the active config (fork-current is the common intent).
    const active = this.state.currentConfigName;
    const matchingTemplate = active
      ? this.templateOptions.find(t => t.stem === active)
      : undefined;
    const firstPredefined = this.templateOptions.find(c => c.source === 'predefined');
    this.templateChoice = (matchingTemplate ?? firstPredefined ?? this.templateOptions[0]).stem;
    this.templateNewName = '';
    this.templateError = '';
    this.templateBusy = false;
    this.templateDialogOpen = true;
    this.menuOpen = false;
  }

  cancelCreateFromTemplate(): void {
    this.templateDialogOpen = false;
    this.templateChoice = '';
    this.templateNewName = '';
    this.templateError = '';
    this.templateBusy = false;
  }

  /** Fetch the template, rewrite `id` to the new stem, persist. */
  confirmCreateFromTemplate(): void {
    const name = this.templateNewName.trim();
    if (!name) { this.templateError = 'Name cannot be empty.'; return; }
    if (/[\\/:*?"<>|]/.test(name)) {
      this.templateError = 'Name contains invalid characters.';
      return;
    }
    if (this.state.predefinedConfigs.some(c => (c.stem === name || c.id === name) && c.source === 'predefined')) {
      this.templateError = `"${name}" collides with a predefined config. Pick a different name.`;
      return;
    }
    if (!this.templateChoice) {
      this.templateError = 'Pick a template first.';
      return;
    }

    this.templateBusy = true;
    this.api.getConfig(this.templateChoice).subscribe({
      next: tpl => {
        const cloned = { ...tpl, id: name } as unknown as Record<string, unknown>;
        this.persistLoadedConfig(name, cloned);
        this.templateDialogOpen = false;
        this.templateChoice = '';
        this.templateNewName = '';
        this.templateError = '';
        this.templateBusy = false;
      },
      error: err => {
        this.templateError = `Failed to fetch template: ${err?.error?.detail ?? err?.message ?? 'unknown error'}`;
        this.templateBusy = false;
        this.cdr.markForCheck();
      },
    });
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

  /** Reason string on failure, null when valid. */
  private validateLoadedConfig(obj: Record<string, unknown>, stem: string): string | null {
    const required = ['id', 'entry', 'edges', 'agents'];
    const missing = required.filter(k => !(k in obj));
    if (missing.length) return `missing required key(s): ${missing.join(', ')}`;
    if (obj['id'] !== stem) {
      return `the JSON's "id" must match the filename. Got id=${JSON.stringify(obj['id'])}, file=${JSON.stringify(stem)}.`;
    }
    return null;
  }

  /** POST the config; on 409 prompt for replacement and retry. */
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
