/** Errors + warnings panels surfaced after Validate/Save. Controlled. */
import { Component, EventEmitter, Input, Output } from '@angular/core';
import { CommonModule } from '@angular/common';

@Component({
  selector: 'app-validation-panels',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './validation-panels.component.html',
  styleUrl: './validation-panels.component.css',
})
export class ValidationPanelsComponent {
  @Input() errors: string[] = [];
  @Input() warnings: string[] = [];

  @Output() dismissErrors = new EventEmitter<void>();
  @Output() dismissWarnings = new EventEmitter<void>();
}
