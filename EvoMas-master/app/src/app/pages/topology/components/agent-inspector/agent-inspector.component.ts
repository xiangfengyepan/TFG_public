/** Right-hand inspector: agent params + tools + prompts editor for the
 * selected node. Controlled — parent owns the canonical AgentBlock and
 * applies mutations on emit. */
import { Component, EventEmitter, Input, Output } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import {
  EvoBoxComponent, EvoSliderComponent, EvoSpinboxComponent,
  EvoSelectComponent, EvoSwitchComponent, EvoHelpPopoverComponent,
} from '../../../../components/index';
import { AgentBlock, AgentTool, AgentType, ToolDescriptor } from '../../../../models/types';

type PromptSlot = 'system' | 'user' | 'proxy' | 'route';

@Component({
  selector: 'app-agent-inspector',
  standalone: true,
  imports: [
    CommonModule, FormsModule,
    EvoBoxComponent, EvoSliderComponent, EvoSpinboxComponent,
    EvoSelectComponent, EvoSwitchComponent, EvoHelpPopoverComponent,
  ],
  templateUrl: './agent-inspector.component.html',
  styleUrl: './agent-inspector.component.css',
})
export class AgentInspectorComponent {
  @Input() selectedAgent: string | null = null;
  @Input() agentBlock: AgentBlock | null = null;
  @Input() agentBadgeColor = '#888';
  @Input() agentLabel = '';
  @Input() isLoadedConfig = false;
  @Input() modelSelectOptions: string[] = [];
  @Input() availableTools: ToolDescriptor[] = [];
  @Input() currentTools: AgentTool[] = [];
  @Input() unusedToolNames: string[] = [];
  @Input() currentAgentType: AgentType | null = null;
  @Input() promptTab: PromptSlot | '' = '';
  @Input() toolParamsError: Record<number, string> = {};

  @Output() field = new EventEmitter<{ key: keyof AgentBlock; value: AgentBlock[keyof AgentBlock] }>();
  @Output() addTool = new EventEmitter<string>();
  @Output() removeTool = new EventEmitter<number>();
  @Output() paramsInput = new EventEmitter<{ idx: number; value: string }>();
  @Output() togglePromptTab = new EventEmitter<PromptSlot>();
  @Output() promptChange = new EventEmitter<{ slot: PromptSlot; value: string }>();

  // Pure helpers (no side effects) used by template.
  @Input() supportsKnob: (knob: string) => boolean = () => true;
  @Input() paramsJson: (idx: number) => string = () => '{}';
  @Input() getPrompt: (slot: PromptSlot) => string = () => '';
  @Input() toolDescription: (name: string) => string = () => '';

  promptSlots: PromptSlot[] = ['system', 'user', 'proxy', 'route'];

  onField<K extends keyof AgentBlock>(key: K, value: AgentBlock[K]): void {
    this.field.emit({ key, value });
  }
}
