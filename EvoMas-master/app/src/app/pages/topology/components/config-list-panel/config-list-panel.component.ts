/** Left rail of the Topology page: lists predefined + loaded configs,
 * with rename / delete affordances on the loaded entries. Pure
 * presentation -- all persistence logic lives on the parent.
 *
 * Collapse state stays on the parent because the center toolbar's
 * `cramped` mode keys on it; the parent owns the signal and feeds the
 * boolean in as an @Input, the child emits a toggle intent. */
import {
  ChangeDetectionStrategy, Component, EventEmitter, Input, Output,
} from '@angular/core';
import { CommonModule } from '@angular/common';

import { ConfigSummary } from '../../../../models/types';
import { EvoBoxComponent } from '../../../../components/index';

@Component({
  selector: 'app-config-list-panel',
  standalone: true,
  imports: [CommonModule, EvoBoxComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './config-list-panel.component.html',
  styleUrl: './config-list-panel.component.css',
})
export class ConfigListPanelComponent {
  @Input() predefinedList: ConfigSummary[] = [];
  @Input() loadedList: ConfigSummary[] = [];
  @Input() currentConfigName: string | null = null;
  @Input() collapsed = false;

  @Output() load            = new EventEmitter<string>();
  @Output() rename          = new EventEmitter<string>();
  @Output() delete          = new EventEmitter<{ stem: string; ev: Event }>();
  @Output() toggleCollapsed = new EventEmitter<void>();
}
