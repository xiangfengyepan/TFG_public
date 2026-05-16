/** Top toolbar: title chip + state chips + 4 button groups + super-step
 * help popover. Controlled — every button click bubbles via an output. */
import { Component, EventEmitter, Input, Output } from '@angular/core';
import { CommonModule } from '@angular/common';
import { EvoButtonComponent, EvoHelpPopoverComponent } from '../../../../components/index';

export interface SuperStep { step: number; nodes: string[]; note?: string; }
export interface SuperStepOutline { steps: SuperStep[]; empty: boolean; }

@Component({
  selector: 'app-graph-toolbar',
  standalone: true,
  imports: [CommonModule, EvoButtonComponent, EvoHelpPopoverComponent],
  templateUrl: './graph-toolbar.component.html',
  styleUrl: './graph-toolbar.component.css',
})
export class GraphToolbarComponent {
  @Input() currentConfigName: string | null = null;
  @Input() hasConfig = false;
  @Input() isLoadedConfig = false;
  @Input() dirty = false;
  @Input() validated = true;
  @Input() addEdgeMode = false;
  @Input() edgeSource: string | null = null;
  @Input() selectedAgent: string | null = null;
  @Input() selectedEdgeId: string | null = null;
  @Input() saveFlash = false;
  @Input() validateFlash = false;
  @Input() saveError = '';
  @Input() outline: SuperStepOutline = { steps: [], empty: true };

  @Output() toggleAddEdge = new EventEmitter<void>();
  @Output() delete = new EventEmitter<void>();
  @Output() rename = new EventEmitter<void>();
  @Output() validate = new EventEmitter<void>();
  @Output() save = new EventEmitter<void>();
  @Output() fit = new EventEmitter<void>();
  @Output() relayout = new EventEmitter<void>();
  @Output() reload = new EventEmitter<void>();
}
