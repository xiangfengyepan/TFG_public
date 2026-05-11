/**
 * Regression — switching configs after a failed load left the graph blank.
 *
 * Earlier the graph host was toggled `[hidden]="!!loadError"`. After a
 * failed load the host became `display:none`; on the next successful
 * load the freshly-added cytoscape elements were measured against a 0×0
 * box (CSS hadn't flipped yet by the time `cy.resize() / layout()` ran)
 * so the graph stayed empty even though `/api/configs/<name>` had
 * returned a config.
 *
 * Fix: the graph host stays mounted + visible at all times; the error
 * panel is an absolute overlay. This spec drives the load → error →
 * recovery flow through the component's HTTP + render pipeline and
 * checks that cytoscape received the recovery config's elements (and
 * that `loadError` cleared).
 */
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { afterAll, beforeAll, describe, expect, it, vi } from 'vitest';

// ── Suppress dev-mode NG0100 noise ──────────────────────────────
// Angular's `checkNoChanges` second-pass runs in a microtask scheduled by
// NgZone after this spec's HTTP flushes mutate currentConfigName. The
// pass fires AFTER the test body has finished its assertions and surfaces
// in vitest in three different ways:
//   1. process.uncaughtException (Node-side)
//   2. window.error (jsdom-side)
//   3. console.error (Angular's internal error reporter logs it directly)
// The component itself is fine — CD timing in the real app keeps both
// passes in sync. Filter all three so the test output stays clean.
interface NodeProcessLike {
  on?: (event: string, listener: (...args: unknown[]) => void) => void;
  off?: (event: string, listener: (...args: unknown[]) => void) => void;
}
const proc = (globalThis as { process?: NodeProcessLike }).process;

const isNG0100 = (val: unknown): boolean => {
  const msg =
    val instanceof Error ? val.message :
    typeof val === 'string' ? val :
    '';
  return msg.includes('ExpressionChangedAfterItHasBeenCheckedError');
};

const onUncaught = (...args: unknown[]) => {
  if (isNG0100(args[0])) return;
  const err = args[0];
  if (err instanceof Error) throw err;
};
const onWindowError = (event: ErrorEvent) => {
  if (isNG0100(event.error) || isNG0100(event.message)) {
    event.preventDefault();
    event.stopImmediatePropagation();
  }
};
const realConsoleError = console.error.bind(console);
const filteredConsoleError = (...args: unknown[]) => {
  if (args.some(isNG0100)) return;
  realConsoleError(...args);
};
beforeAll(() => {
  proc?.on?.('uncaughtException', onUncaught);
  if (typeof window !== 'undefined') window.addEventListener('error', onWindowError, true);
  console.error = filteredConsoleError;
});
afterAll(() => {
  proc?.off?.('uncaughtException', onUncaught);
  if (typeof window !== 'undefined') window.removeEventListener('error', onWindowError, true);
  console.error = realConsoleError;
});

import type { ConfigSummary, UnifiedConfig } from '../../models/types';

// ── cytoscape mock ───────────────────────────────────────────────
// vi.hoisted lets the factory closure reference an outer object that
// survives across the spec; we read `cyState.fake` to assert calls.
const cyState = vi.hoisted(() => {
  const make = () => {
    const empty = { remove: vi.fn(), length: 0, forEach: () => {}, map: () => [] };
    // Fake host with positive dimensions so scheduleStableLayout's polling
    // succeeds on the first attempt — otherwise it'd retry forever.
    const fakeHost = { offsetWidth: 800, offsetHeight: 600 } as unknown as HTMLElement;
    const fake = {
      destroy: vi.fn(),
      elements: vi.fn(() => empty),
      add: vi.fn(),
      resize: vi.fn(),
      layout: vi.fn(() => ({ run: vi.fn() })),
      fit: vi.fn(),
      on: vi.fn(),
      $: vi.fn(() => empty),
      getElementById: vi.fn(() => ({ ...empty, removeClass: vi.fn(), addClass: vi.fn() })),
      nodes: vi.fn(() => empty),
      container: vi.fn(() => fakeHost),
    };
    return fake;
  };
  return { fake: make(), make };
});

vi.mock('cytoscape', () => ({
  __esModule: true,
  default: vi.fn(() => {
    cyState.fake = cyState.make();
    return cyState.fake;
  }),
}));

// rAF: fire synchronously so deferred resize/layout runs within the same
// tick as the HTTP flush — keeps the spec tight and deterministic.
const rafSpy = vi.fn((cb: FrameRequestCallback) => {
  cb(performance.now());
  return 1 as unknown as number;
});
vi.stubGlobal('requestAnimationFrame', rafSpy);

import { TopologyComponent } from './topology.component';

const BASE = 'http://localhost:8000/api';

const STAR_SUMMARIES: ConfigSummary[] = [
  { stem: 'star',     id: 'star',     description: '', source: 'predefined' },
  { stem: 'evo-star', id: 'evo-star', description: '', source: 'predefined' },
];

const STAR_CFG = {
  id: 'star',
  description: '',
  entry: 'orchestrator',
  end: 'orchestrator',
  edges: [{ from: 'orchestrator', to: 'localizator' }],
  agents: {
    orchestrator: { class: 'OrchestratorAgent' },
    localizator:  { class: 'LocalizatorAgent' },
  },
} as unknown as UnifiedConfig;

const EVO_STAR_CFG = {
  id: 'evo-star',
  description: '',
  entry: 'manager_agent',
  end: 'manager_agent',
  edges: [{ from: 'manager_agent', to: 'localize_agent' }],
  agents: {
    manager_agent:  { class: 'ManagerAgent' },
    localize_agent: { class: 'LocalizeAgent' },
  },
} as unknown as UnifiedConfig;

/** Pull node ids out of cytoscape's `add(elements)` argument. Edges have a
 * `source` field on `data`; nodes don't. The virtual boundary nodes
 * (`__START__` / `__END__`) are filtered out so the assertions stay focused
 * on the real agent set. */
function nodeIdsFromAdd(elements: { data: Record<string, unknown> }[]): string[] {
  return elements
    .filter(e => !('source' in e.data))
    .map(e => String(e.data['id']))
    .filter(id => id !== '__START__' && id !== '__END__')
    .sort();
}

describe('TopologyComponent · graph re-renders after error → success config switch', () => {
  let fixture: ComponentFixture<TopologyComponent>;
  let component: TopologyComponent;
  let http: HttpTestingController;

  function flushOpeningRequests(initialCfg: UnifiedConfig | null) {
    // ngOnInit fires four parallel HTTP requests; flush them in any order.
    http.expectOne(`${BASE}/models`).flush([]);
    http.expectOne(`${BASE}/tools`).flush([]);
    http.expectOne(`${BASE}/agent-types`).flush([]);
    http.expectOne(`${BASE}/configs`).flush(STAR_SUMMARIES);
    if (initialCfg) {
      // After /api/configs lands, the component auto-loads the first
      // (preferring evo-star).
      http.expectOne(`${BASE}/configs/${initialCfg.id}`).flush(initialCfg);
    }
  }

  beforeEach(async () => {
    cyState.fake = cyState.make();
    rafSpy.mockClear();

    await TestBed.configureTestingModule({
      imports: [TopologyComponent],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(TopologyComponent);
    component = fixture.componentInstance;
    http = TestBed.inject(HttpTestingController);

    fixture.detectChanges();             // triggers ngOnInit
    flushOpeningRequests(EVO_STAR_CFG);  // initial load is evo-star
  });

  afterEach(() => {
    // Tear down the component before the test ends. Without this, the
    // configChanged subscription's zone-scheduled CD pass leaks past the
    // assertions and Angular's dev-mode checkNoChanges then fires a
    // bogus NG0100 (because currentConfigName changed mid-flight).
    // fixture.destroy unsubscribes the component's subjects + cancels
    // any pending CD, eliminating the unhandled-exception noise.
    fixture.destroy();
  });

  it('cytoscape receives the recovery config elements after error → success', async () => {
    // ── 1. Failing config load ────────────────────────────────
    component.loadPredefined('star');
    http.expectOne(`${BASE}/configs/star`)
      .flush({ detail: 'boom' }, { status: 500, statusText: 'Internal Server Error' });

    expect(component.loadError, 'failure must surface an error message').toContain('Failed to load');

    // After the failure, the component should have dropped the previous
    // graph contents (so the user doesn't think they're still looking at
    // the previous config). cy.elements() is the entry point to wipe.
    expect(cyState.fake.elements).toHaveBeenCalled();

    // Reset add()/resize history so we can assert the recovery path cleanly.
    cyState.fake.add.mockClear();
    cyState.fake.resize.mockClear();

    // ── 2. Recovery — successful load of the same name ────────
    component.loadPredefined('star');
    http.expectOne(`${BASE}/configs/star`).flush(STAR_CFG);

    expect(component.loadError, 'recovery must clear the error').toBe('');

    // The cytoscape mock should have received star's two nodes (and one
    // edge). cy.add() runs synchronously now — no rAF deferral — and
    // cy.resize() / cy.fit() follow immediately on the same tick.
    expect(cyState.fake.add).toHaveBeenCalled();
    const lastAddArg = cyState.fake.add.mock.calls.at(-1)?.[0] as
      { data: Record<string, unknown> }[];
    expect(nodeIdsFromAdd(lastAddArg))
      .toEqual(['localizator', 'orchestrator']);
    expect(cyState.fake.resize).toHaveBeenCalled();

    // Wait a macrotask to drain NgZone-scheduled CD passes so the dev-mode
    // checkNoChanges pass runs while the test's error suppressor is still
    // attached.
    await new Promise<void>(r => setTimeout(r, 0));
  });

  it('graph host is always mounted (no [hidden] on .graph-wrap)', async () => {
    // Initial successful load already happened; verify the host is in the DOM
    // and unhidden.
    const wrap = fixture.nativeElement.querySelector('.graph-wrap') as HTMLElement;
    expect(wrap, 'graph host must be in the DOM').toBeTruthy();
    expect(wrap.hasAttribute('hidden'), 'no [hidden] on graph-wrap').toBe(false);

    // Force a failure and verify the host is STILL mounted/unhidden — the
    // error panel overlays it instead of replacing it.
    component.loadPredefined('star');
    http.expectOne(`${BASE}/configs/star`)
      .flush({ detail: 'fail' }, { status: 500, statusText: 'Internal Server Error' });

    expect(component.loadError).toBeTruthy();
    expect(wrap.hasAttribute('hidden')).toBe(false);

    await new Promise<void>(r => setTimeout(r, 0));
  });
});
