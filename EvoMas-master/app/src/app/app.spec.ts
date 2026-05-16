import '@angular/compiler';
import { describe, expect, it, vi } from 'vitest';
import { ChangeDetectorRef } from '@angular/core';
import { of, throwError } from 'rxjs';
import { App } from './app';
import { ApiService } from './services/api.service';
import { TopologyStateService } from './services/topology-state.service';

function makeApp(getHealth = () => of({ status: 'ok' })): App {
  const api = {
    getHealth: vi.fn(getHealth),
    apiHost: 'localhost:8000',
  } as unknown as ApiService;
  const cdr = { markForCheck: vi.fn() } as unknown as ChangeDetectorRef;
  return new App(api, new TopologyStateService(), cdr);
}

describe('App health probe', () => {
  it('flips apiOnline to true on a successful probe', () => {
    const app = makeApp();
    app.ngOnInit();
    expect(app.apiOnline).toBe(true);
    expect(app.apiHost).toBe('localhost:8000');
    app.ngOnDestroy();
  });

  it('flips apiOnline to false on a failed probe', () => {
    const app = makeApp(() => throwError(() => new Error('down')));
    app.ngOnInit();
    expect(app.apiOnline).toBe(false);
    app.ngOnDestroy();
  });
});
