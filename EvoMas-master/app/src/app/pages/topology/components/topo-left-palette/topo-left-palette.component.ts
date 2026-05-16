/** Left panel: predefined + loaded config lists. Controlled — parent owns
 * the config catalog and active selection; this component only emits clicks. */
import { Component, EventEmitter, Input, Output } from '@angular/core';
import { CommonModule } from '@angular/common';
import { EvoBoxComponent } from '../../../../components/index';
import { ConfigSummary } from '../../../../models/types';

@Component({
  selector: 'app-topo-left-palette',
  standalone: true,
  imports: [CommonModule, EvoBoxComponent],
  templateUrl: './topo-left-palette.component.html',
  styleUrl: './topo-left-palette.component.css',
})
export class TopoLeftPaletteComponent {
  @Input() predefinedList: ConfigSummary[] = [];
  @Input() loadedList: ConfigSummary[] = [];
  @Input() currentConfigName: string | null = null;

  @Output() loadConfig = new EventEmitter<string>();
  @Output() renameLoaded = new EventEmitter<string>();
  @Output() deleteLoaded = new EventEmitter<{ stem: string; ev: Event }>();
}
