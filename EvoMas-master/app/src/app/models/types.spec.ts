import { describe, expect, it } from 'vitest';
import { suggestNodeId } from './types';

describe('suggestNodeId', () => {
  it('returns <type>_1 when nothing is taken', () => {
    expect(suggestNodeId('Localizator', new Set())).toBe('localizator_1');
  });

  it('snake-cases slashes and spaces', () => {
    expect(suggestNodeId('Helper/Proxy', new Set())).toBe('helper_proxy_1');
    expect(suggestNodeId('Bug reproduction', new Set())).toBe('bug_reproduction_1');
  });

  it('strips characters that are not alphanumeric or underscore', () => {
    expect(suggestNodeId('Reviewer!?', new Set())).toBe('reviewer_1');
  });

  it('increments past the highest taken suffix', () => {
    const taken = new Set(['patcher_1', 'patcher_2']);
    expect(suggestNodeId('Patcher', taken)).toBe('patcher_3');
  });

  it('does not collide with existing node ids', () => {
    const taken = new Set(['localizator_1']);
    expect(suggestNodeId('Localizator', taken)).toBe('localizator_2');
  });
});
