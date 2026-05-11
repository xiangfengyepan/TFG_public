import { Component, Input, forwardRef } from '@angular/core';
import { ControlValueAccessor, NG_VALUE_ACCESSOR, FormsModule } from '@angular/forms';
import { CommonModule } from '@angular/common';

export interface SelectOption { value: string; label: string; }

@Component({
  selector: 'evo-select',
  standalone: true,
  imports: [CommonModule, FormsModule],
  template: `
    <div class="evo-select-wrap">
      @if (label) { <label class="evo-label">{{ label }}</label> }
      <div class="evo-select-box" [class.disabled]="isDisabled">
        <select
          class="evo-select"
          [disabled]="isDisabled"
          [ngModel]="value"
          (ngModelChange)="onValueChange($event)">
          @for (opt of normalizedOptions; track opt.value) {
            <option [value]="opt.value">{{ opt.label }}</option>
          }
        </select>
        <span class="evo-select-arrow">▾</span>
      </div>
    </div>
  `,
  styleUrl: './evo-select.component.css',
  providers: [{
    provide: NG_VALUE_ACCESSOR,
    useExisting: forwardRef(() => EvoSelectComponent),
    multi: true,
  }],
})
export class EvoSelectComponent implements ControlValueAccessor {
  @Input() label = '';
  @Input() set options(v: string[] | SelectOption[]) {
    this.normalizedOptions = (v as any[]).map(o =>
      typeof o === 'string' ? { value: o, label: o } : o
    );
  }

  value = '';
  isDisabled = false;
  normalizedOptions: SelectOption[] = [];

  private onChange: (v: string) => void = () => {};
  private onTouched: () => void = () => {};

  onValueChange(v: string): void {
    this.value = v;
    this.onChange(v);
    this.onTouched();
  }

  writeValue(v: string): void { this.value = v ?? ''; }
  registerOnChange(fn: any): void { this.onChange = fn; }
  registerOnTouched(fn: any): void { this.onTouched = fn; }
  setDisabledState(d: boolean): void { this.isDisabled = d; }
}
