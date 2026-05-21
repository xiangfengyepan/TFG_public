/** Bottom palette strip: one draggable chip per canonical AGENT_TYPE.
 * The chip + its variant dropdown live in `evo-agent-type-picker`;
 * this component is just the layout shell + the parent-bound variant
 * selection. Drag-start payload is handled inside the chip itself. */
import {
  ChangeDetectionStrategy, Component, EventEmitter, Input, Output,
} from '@angular/core';
import { CommonModule } from '@angular/common';

import { AgentType, AgentVariant } from '../../../../models/types';
import { EvoAgentTypePickerComponent } from '../../../../components/index';

@Component({
  selector: 'app-topology-palette',
  standalone: true,
  imports: [CommonModule, EvoAgentTypePickerComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './topology-palette.component.html',
  styleUrl: './topology-palette.component.css',
})
export class TopologyPaletteComponent {
  @Input() agentTypes: AgentType[] = [];
  @Input() selectedVariantByType: Record<string, string> = {};
  @Input() isLoadedConfig = false;

  @Output() variantChange = new EventEmitter<{ type: string; key: string }>();

  variantsFor(type: string): AgentVariant[] {
    return this.agentTypes.find(t => t.type === type)?.variants ?? [];
  }

  selectedVariantKey(type: string): string {
    const stored = this.selectedVariantByType[type];
    if (stored) return stored;
    const vs = this.variantsFor(type);
    return vs.length ? vs[0].key : `evomas:${type}`;
  }

  onVariantChange(type: string, key: string): void {
    this.variantChange.emit({ type, key });
  }
}
