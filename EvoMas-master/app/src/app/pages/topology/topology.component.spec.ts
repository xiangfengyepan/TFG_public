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
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';

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
      // refreshLoopbackCurves iterates `cy.edges('.edge-loopback')` after
      // every render. The `empty.forEach` no-op path is all the spec needs.
      edges: vi.fn(() => empty),
      container: vi.fn(() => fakeHost),
      // On-canvas zoom controls + readout: syncZoomReadout calls zoom(),
      // stepZoom calls zoom()/minZoom()/maxZoom()/width()/height() and
      // then zoom({level, renderedPosition}). One vi.fn() per method with
      // sane defaults is enough — no spec inspects the written values.
      zoom: vi.fn(() => 1),
      minZoom: vi.fn(() => 0.65),
      maxZoom: vi.fn(() => 2.5),
      width: vi.fn(() => 800),
      height: vi.fn(() => 600),
      // syncBgPan reads cy.pan() each tick to drive the parallax
      // background. (0,0) means "no translate" — bgTransform stays
      // identity, the bg-stack renders unmoved. Specs don't inspect it.
      pan: vi.fn(() => ({ x: 0, y: 0 })),
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
import { TopologyStateService } from '../../services/topology-state.service';

const BASE = 'http://localhost:8000/api';

const CHAIN_SUMMARIES: ConfigSummary[] = [
  { stem: 'chain',      id: 'chain',      description: '', source: 'predefined' },
  { stem: 'openhands', id: 'openhands', description: '', source: 'predefined' },
];

const CHAIN_CFG = {
  id: 'chain',
  description: '',
  entry: 'orchestrator',
  end: 'orchestrator',
  edges: [{ from: 'orchestrator', to: 'locator' }],
  agents: {
    orchestrator: { class: 'Orchestrator' },
    locator:  { class: 'LocatorAgent' },
  },
} as unknown as UnifiedConfig;

const EVO_CHAIN_CFG = {
  id: 'chain',
  description: '',
  entry: 'orchestrator',
  end: 'orchestrator',
  edges: [{ from: 'orchestrator', to: 'locator' }],
  agents: {
    orchestrator: { class: 'Orchestrator' },
    locator:  { class: 'Locator' },
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
    http.expectOne(`${BASE}/configs`).flush(CHAIN_SUMMARIES);
    if (initialCfg) {
      // After /api/configs lands, the component auto-loads the first
      // (preferring `chain`).
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
    flushOpeningRequests(EVO_CHAIN_CFG);  // initial load is `chain`
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
    component.loadPredefined('chain');
    http.expectOne(`${BASE}/configs/chain`)
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
    component.loadPredefined('chain');
    http.expectOne(`${BASE}/configs/chain`).flush(CHAIN_CFG);

    expect(component.loadError, 'recovery must clear the error').toBe('');

    // The cytoscape mock should have received chain's two nodes (and one
    // edge). cy.add() runs synchronously now — no rAF deferral — and
    // cy.resize() / cy.fit() follow immediately on the same tick.
    expect(cyState.fake.add).toHaveBeenCalled();
    const lastAddArg = cyState.fake.add.mock.calls.at(-1)?.[0] as
      { data: Record<string, unknown> }[];
    expect(nodeIdsFromAdd(lastAddArg))
      .toEqual(['locator', 'orchestrator']);
    expect(cyState.fake.resize).toHaveBeenCalled();

    // Wait a macrotask to drain NgZone-scheduled CD passes so the dev-mode
    // checkNoChanges pass runs while the test's error suppressor is still
    // attached.
    await new Promise<void>(r => setTimeout(r, 0));
  });

  // ── Reset-to-defaults helpers + prompt-tab default-vs-custom chip ──
  // These exercise the three per-section reset buttons (TODO 2) plus the
  // `isCustomPrompt` getter used by the prompt-tab chip (TODO 3). The
  // setup pivots the freshly-loaded `chain` config into a "loaded" (i.e.
  // writable) config and prepopulates an `AgentType` catalog so the
  // class → type lookup can resolve the active block.
  function makeWritable(): TopologyStateService {
    // Tear down the live DOM-attached fixture BEFORE mutating block fields.
    // The parent beforeEach loaded EVO_CHAIN_CFG and rendered it; any
    // synchronous mutation (resetParams overwriting num_predict from 10
    // back to the catalog default) would otherwise trip dev-mode
    // checkNoChanges (NG0100) on the next CD pass. We don't need the DOM
    // for these tests — we exercise the methods directly.
    fixture.destroy();
    const svc = TestBed.inject(TopologyStateService);
    svc.predefinedConfigs = [
      { stem: 'chain', id: 'chain', description: '', source: 'loaded' },
    ];
    svc.currentConfigName = 'chain';
    svc.selectedAgent = 'orchestrator';
    // Inject an agent-type catalog entry that matches the orchestrator
    // block's class so resetParams/resetTools/resetPrompts can find their
    // defaults. Bypasses the private classToType via `as any` since we
    // don't want the public API surface to grow just for the test.
    component.agentTypes = [{
      type: 'Orchestrator',
      color: '#abc',
      description: '',
      class: 'Orchestrator',
      default_system: 'default-system',
      default_user: 'default-user',
      default_tools: ['read_file', 'finish'],
      default_config: {
        model: 'qwen3.5:9b',
        think: true,
        temperature: 0.0,
        num_ctx: 2048,
      },
    }];
    (component as unknown as { classToType: Record<string, string> }).classToType = {
      'Orchestrator': 'Orchestrator',
    };
    return svc;
  }

  it('resetParams overwrites only Ollama knobs and leaves prompts/tools intact', () => {
    const svc = makeWritable();
    const block = svc.selectedAgentBlock()!;
    block.temperature = 0.99;
    block.tools = [{ name: 'apply_patch', params: { foo: 'bar' } }];
    block.prompts = { system: 'custom-sys', user: 'custom-usr' };

    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true);
    component.resetParams();
    confirmSpy.mockRestore();

    expect(block.temperature).toBe(0.0);
    expect(block.num_ctx).toBe(2048);
    expect(block.tools).toEqual([{ name: 'apply_patch', params: { foo: 'bar' } }]);
    expect(block.prompts).toEqual({ system: 'custom-sys', user: 'custom-usr' });
    expect(svc.dirty).toBe(true);
  });

  it('resetTools re-applies type default_tools and leaves params/prompts intact', () => {
    const svc = makeWritable();
    const block = svc.selectedAgentBlock()!;
    block.tools = [{ name: 'apply_patch', params: { foo: 'bar' } }];
    block.temperature = 0.99;
    block.prompts = { system: 'custom-sys' };

    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true);
    component.resetTools();
    confirmSpy.mockRestore();

    expect(block.tools).toEqual([
      { name: 'read_file', params: {} },
      { name: 'finish',    params: {} },
    ]);
    expect(block.temperature).toBe(0.99);
    expect(block.prompts).toEqual({ system: 'custom-sys' });
    expect(svc.dirty).toBe(true);
  });

  it('resetPrompts clears block.prompts and leaves params/tools intact', () => {
    const svc = makeWritable();
    const block = svc.selectedAgentBlock()!;
    block.prompts = { system: 'custom-sys', user: 'custom-usr', proxy: 'p' };
    block.tools = [{ name: 'apply_patch', params: { foo: 'bar' } }];
    block.temperature = 0.99;

    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true);
    component.resetPrompts();
    confirmSpy.mockRestore();

    expect(block.prompts).toEqual({});
    expect(block.tools).toEqual([{ name: 'apply_patch', params: { foo: 'bar' } }]);
    expect(block.temperature).toBe(0.99);
    expect(svc.dirty).toBe(true);
  });

  it('reset methods short-circuit when confirm() is dismissed', () => {
    const svc = makeWritable();
    const block = svc.selectedAgentBlock()!;
    block.temperature = 0.99;
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false);
    svc.dirty = false;
    component.resetParams();
    confirmSpy.mockRestore();

    expect(block.temperature).toBe(0.99);
    expect(svc.dirty).toBe(false);
  });

  it('graph host is always mounted (no [hidden] on .graph-wrap)', async () => {
    // Initial successful load already happened; verify the host is in the DOM
    // and unhidden.
    const wrap = fixture.nativeElement.querySelector('.graph-wrap') as HTMLElement;
    expect(wrap, 'graph host must be in the DOM').toBeTruthy();
    expect(wrap.hasAttribute('hidden'), 'no [hidden] on graph-wrap').toBe(false);

    // Force a failure and verify the host is STILL mounted/unhidden — the
    // error panel overlays it instead of replacing it.
    component.loadPredefined('chain');
    http.expectOne(`${BASE}/configs/chain`)
      .flush({ detail: 'fail' }, { status: 500, statusText: 'Internal Server Error' });

    expect(component.loadError).toBeTruthy();
    expect(wrap.hasAttribute('hidden')).toBe(false);

    await new Promise<void>(r => setTimeout(r, 0));
  });
});
