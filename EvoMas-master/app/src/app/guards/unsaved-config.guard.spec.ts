import '@angular/compiler';
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { TestBed } from '@angular/core/testing';
import { unsavedConfigGuard } from './unsaved-config.guard';
import { TopologyStateService } from '../services/topology-state.service';
import type { TopologyComponent } from '../pages/topology/topology.component';

function fakeComponent(isLoadedConfig: boolean): TopologyComponent {
  return { isLoadedConfig } as unknown as TopologyComponent;
}

describe('unsavedConfigGuard', () => {
  let confirmSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true);
    TestBed.resetTestingModule();
    TestBed.configureTestingModule({ providers: [TopologyStateService] });
  });

  afterEach(() => {
    confirmSpy.mockRestore();
  });

  function runGuard(
    component: TopologyComponent,
    nextUrl = '/inference',
  ): boolean {
    // The guard's body only returns booleans (no UrlTree / Observable
    // branches), so this cast is safe even though the static type of
    // CanDeactivateFn is wider. We stub the RouterStateSnapshot to
    // expose `.url` for the leave-and-reload path.
    const nextState = { url: nextUrl } as never;
    return TestBed.runInInjectionContext(() =>
      unsavedConfigGuard(
        component,
        null as never, null as never, nextState,
      ),
    ) as boolean;
  }

  it('returns true (no warning) when there are no unsaved edits', () => {
    const svc = TestBed.inject(TopologyStateService);
    svc.dirty = false;
    const allowed = runGuard(fakeComponent(true));
    expect(allowed).toBe(true);
    expect(confirmSpy).not.toHaveBeenCalled();
  });

  it('returns true (no warning) when the active config is read-only', () => {
    const svc = TestBed.inject(TopologyStateService);
    svc.dirty = true;
    svc.currentConfigName = 'chain';
    const allowed = runGuard(fakeComponent(false));
    expect(allowed).toBe(true);
    expect(confirmSpy).not.toHaveBeenCalled();
  });

  it('prompts the user when dirty + loaded config; "Stay" cancels navigation', () => {
    const svc = TestBed.inject(TopologyStateService);
    svc.dirty = true;
    svc.currentConfigName = 'my-draft';
    confirmSpy.mockReturnValueOnce(false);
    expect(runGuard(fakeComponent(true))).toBe(false);
    expect(confirmSpy).toHaveBeenCalledTimes(1);
    expect(confirmSpy.mock.calls[0][0]).toContain('my-draft');
  });

  it('"Leave" returns false (Angular nav cancelled — browser does the real one)', () => {
    const svc = TestBed.inject(TopologyStateService);
    svc.dirty = true;
    svc.currentConfigName = 'my-draft';
    confirmSpy.mockReturnValueOnce(true);
    // The guard's contract on accept is: cancel Angular's pending
    // navigation (return false) and kick off a full-page reload to the
    // destination URL via `window.location.assign`. We can't stub
    // `window.location.assign` in jsdom — the property is read-only —
    // so we only verify the contract surface that's testable: the
    // returned boolean. The `assign()` call itself is exercised by
    // the manual smoke-test in the plan's verification section.
    expect(runGuard(fakeComponent(true), '/inference')).toBe(false);
    expect(confirmSpy).toHaveBeenCalledTimes(1);
  });
});
