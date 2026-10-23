import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { createContext, runInContext } from 'node:vm';

import ts from 'typescript';

interface Point { x: number; y: number }

class FakeClassList {
  private tokens = new Set<string>();
  add(...tokens: string[]): void { for (const token of tokens) this.tokens.add(token); }
  remove(...tokens: string[]): void { for (const token of tokens) this.tokens.delete(token); }
  contains(token: string): boolean { return this.tokens.has(token); }
}

class FakeElement extends EventTarget {
  classList = new FakeClassList();
  textContent: string | null = '';
  hidden = false;
  ownerDocument?: { activeElement: FakeElement | null };
  private listeners = new Map<string, Set<EventListenerOrEventListenerObject>>();

  override addEventListener(type: string, callback: EventListenerOrEventListenerObject | null, options?: AddEventListenerOptions | boolean): void {
    super.addEventListener(type, callback, options);
    if (callback === null) return;
    const callbacks = this.listeners.get(type) ?? new Set<EventListenerOrEventListenerObject>();
    callbacks.add(callback);
    this.listeners.set(type, callbacks);
  }

  override removeEventListener(type: string, callback: EventListenerOrEventListenerObject | null, options?: EventListenerOptions | boolean): void {
    super.removeEventListener(type, callback, options);
    if (callback !== null) this.listeners.get(type)?.delete(callback);
  }

  listenerCount(type: string): number { return this.listeners.get(type)?.size ?? 0; }
  fire(type: string): void { this.dispatchEvent(new Event(type)); }
}

class FakeLeafletEvents {
  private listeners = new Map<string, Set<() => void>>();

  on(type: string, listener: () => void): this {
    const callbacks = this.listeners.get(type) ?? new Set<() => void>();
    callbacks.add(listener);
    this.listeners.set(type, callbacks);
    return this;
  }

  off(type: string, listener: () => void): this { this.listeners.get(type)?.delete(listener); return this; }
  fire(type: string): void { for (const listener of [...(this.listeners.get(type) ?? [])]) listener(); }
  listenerCount(type: string): number { return this.listeners.get(type)?.size ?? 0; }
}

class FakeMap extends FakeLeafletEvents {
  size: Point = { x: 100, y: 80 };
  getSize(): Point { return this.size; }
  latLngToContainerPoint(coordinate: Point): Point { return coordinate; }
}

class FakeMarker extends FakeLeafletEvents {
  coordinate: Point;
  element: FakeElement | null;
  tooltipOpen = false;
  tooltipOpenCalls = 0;

  constructor(coordinate: Point, element: FakeElement | null = new FakeElement()) {
    super();
    this.coordinate = coordinate;
    this.element = element;
  }

  getLatLng(): Point { return this.coordinate; }
  getElement(): FakeElement | null { return this.element; }
  openTooltip(): this { this.tooltipOpen = true; this.tooltipOpenCalls++; this.fire('tooltipopen'); return this; }
  closeTooltip(): this { this.tooltipOpen = false; return this; }
}

interface Candidate {
  id: string;
  rank: number;
  title: string;
  card: FakeElement;
  marker: FakeMarker | null;
  hint: FakeElement;
}

interface MapViewHelpers {
  containsPoint(point: Point | null, size: Point): boolean;
  create(options: { map: FakeMap | null; countLabel: FakeElement }): { setCandidates(candidates: Candidate[]): void };
}

const source = readFileSync(new URL('../../src/archsearch/frontend/map-view.ts', import.meta.url), 'utf8');
const compiled = ts.transpileModule(source, {
  fileName: 'map-view.ts',
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.None, strict: true },
  reportDiagnostics: true,
});
assert.equal(compiled.diagnostics?.filter((item) => item.category === ts.DiagnosticCategory.Error).length, 0);
const candidate: unknown = runInContext(`${compiled.outputText}\nArchSearchMapView;`, createContext({}));
assert.ok(typeof candidate === 'object' && candidate !== null);
assert.ok('containsPoint' in candidate && typeof candidate.containsPoint === 'function');
assert.ok('create' in candidate && typeof candidate.create === 'function');
const helpers = candidate as MapViewHelpers;

function item(id: string, coordinate: Point | null = { x: 20, y: 30 }): Candidate {
  return { id, rank: 1, title: `Original source ${id}`, card: new FakeElement(), marker: coordinate === null ? null : new FakeMarker(coordinate), hint: new FakeElement() };
}

function setup() {
  const map = new FakeMap();
  const countLabel = new FakeElement();
  return { map, countLabel, view: helpers.create({ map, countLabel }) };
}

function assertPreview(candidate: Candidate, expected: boolean): void {
  assert.equal(candidate.card.classList.contains('is-preview'), expected, `${candidate.id}: card preview`);
  if (candidate.marker) {
    if (candidate.marker.element) assert.equal(candidate.marker.element.classList.contains('is-preview'), expected, `${candidate.id}: marker preview`);
    assert.equal(candidate.marker.tooltipOpen, expected, `${candidate.id}: tooltip`);
  }
}

test('viewport containment includes each boundary and the visible origin', () => {
  const size = { x: 100, y: 80 };
  for (const point of [{ x: 0, y: 0 }, { x: 100, y: 0 }, { x: 0, y: 80 }, { x: 100, y: 80 }, { x: 50, y: 40 }]) {
    assert.equal(helpers.containsPoint(point, size), true, JSON.stringify(point));
  }
});

test('viewport containment refuses points just outside every edge', () => {
  const size = { x: 100, y: 80 };
  for (const point of [{ x: -0.01, y: 40 }, { x: 100.01, y: 40 }, { x: 50, y: -0.01 }, { x: 50, y: 80.01 }]) {
    assert.equal(helpers.containsPoint(point, size), false, JSON.stringify(point));
  }
});

test('missing or nonfinite projected coordinates are never counted as visible', () => {
  assert.equal(helpers.containsPoint(null, { x: 100, y: 80 }), false);
  for (const value of [Number.NaN, Number.POSITIVE_INFINITY, Number.NEGATIVE_INFINITY]) {
    assert.equal(helpers.containsPoint({ x: value, y: 20 }, { x: 100, y: 80 }), false);
    assert.equal(helpers.containsPoint({ x: 20, y: value }, { x: 100, y: 80 }), false);
  }
});

test('zero, negative and nonfinite viewport dimensions are invalid', () => {
  for (const value of [0, -1, Number.NaN, Number.POSITIVE_INFINITY, Number.NEGATIVE_INFINITY]) {
    assert.equal(helpers.containsPoint({ x: 0, y: 0 }, { x: value, y: 80 }), false);
    assert.equal(helpers.containsPoint({ x: 0, y: 0 }, { x: 100, y: value }), false);
  }
});

test('the initial empty view reports zero returned candidates', () => {
  const { countLabel } = setup();
  assert.equal(countLabel.hidden, false);
  assert.equal(countLabel.textContent, '当前地图范围内 0 / 本次返回 0');
});

test('viewport counts distinguish visible, outside and missing representative points', () => {
  const { view, countLabel } = setup();
  const inside = item('inside'); const outside = item('outside', { x: 101, y: 40 }); const missing = item('missing', null);
  view.setCandidates([inside, outside, missing]);
  assert.equal(countLabel.textContent, '当前地图范围内 1 / 本次返回 3');
  assert.equal(inside.hint.hidden, true);
  assert.equal(outside.hint.hidden, false); assert.equal(outside.hint.textContent, '当前地图范围外');
  assert.equal(missing.hint.hidden, false); assert.equal(missing.hint.textContent, '无可用代表点');
});

for (const event of ['moveend', 'zoomend', 'resize']) {
  test(`the visible count and hints update after ${event}`, () => {
    const { view, map, countLabel } = setup();
    const candidate = item('moving', { x: 120, y: 40 });
    view.setCandidates([candidate]); assert.equal(candidate.hint.hidden, false);
    map.size = { x: 120, y: 80 }; map.fire(event);
    assert.equal(candidate.hint.hidden, true); assert.equal(countLabel.textContent, '当前地图范围内 1 / 本次返回 1');
    map.size = { x: 119, y: 80 }; map.fire(event);
    assert.equal(candidate.hint.hidden, false); assert.equal(countLabel.textContent, '当前地图范围内 0 / 本次返回 1');
  });
}

test('an unavailable map hides counts and viewport hints without implying missing source coordinates', () => {
  const countLabel = new FakeElement(); const view = helpers.create({ map: null, countLabel });
  const candidate = item('without-map'); view.setCandidates([candidate]);
  assert.equal(countLabel.hidden, true); assert.equal(countLabel.textContent, '');
  assert.equal(candidate.hint.hidden, true); assert.equal(candidate.hint.textContent, '');
  candidate.card.fire('focus'); assertPreview(candidate, true);
});

test('card hover previews both representations and opens its original tooltip', () => {
  const { view } = setup(); const candidate = item('a'); view.setCandidates([candidate]);
  candidate.card.fire('mouseenter'); assertPreview(candidate, true);
  candidate.card.fire('mouseleave'); assertPreview(candidate, false);
});

test('marker hover previews the associated result card without changing selection', () => {
  const { view } = setup(); const first = item('a'); const second = item('b');
  first.card.classList.add('is-selected'); first.marker?.element?.classList.add('is-selected'); view.setCandidates([first, second]);
  second.marker?.fire('mouseover'); assertPreview(first, false); assertPreview(second, true);
  assert.equal(first.card.classList.contains('is-selected'), true); assert.equal(second.card.classList.contains('is-selected'), false);
  second.marker?.fire('mouseout'); assertPreview(second, false);
});

test('keyboard focus has priority over the latest pointer and restores pointer preview after blur', () => {
  const { view } = setup(); const first = item('a'); const second = item('b'); const third = item('c'); view.setCandidates([first, second, third]);
  first.card.fire('mouseenter'); second.card.fire('focus'); third.marker?.fire('mouseover');
  assertPreview(first, false); assertPreview(second, true); assertPreview(third, false);
  second.card.fire('blur'); assertPreview(second, false); assertPreview(third, true);
  third.marker?.fire('mouseout'); assertPreview(third, false);
});

test('a stale card leave cannot remove the newer marker pointer preview', () => {
  const { view } = setup(); const first = item('a'); const second = item('b'); view.setCandidates([first, second]);
  first.card.fire('mouseenter'); second.marker?.fire('mouseover'); first.card.fire('mouseleave');
  assertPreview(first, false); assertPreview(second, true);
});

test('card-to-marker pointer transfer on the same candidate survives the old leave event', () => {
  const { view } = setup(); const candidate = item('a'); view.setCandidates([candidate]);
  candidate.card.fire('mouseenter'); candidate.marker?.fire('mouseover'); candidate.marker?.closeTooltip(); candidate.card.fire('mouseleave');
  assertPreview(candidate, true);
  candidate.marker?.fire('mouseout'); assertPreview(candidate, false);
});

test('a stale blur cannot remove focus preview from a newer marker', () => {
  const { view } = setup(); const first = item('a'); const second = item('b'); view.setCandidates([first, second]);
  first.card.fire('focus'); second.marker?.element?.fire('focus'); first.card.fire('blur');
  assertPreview(first, false); assertPreview(second, true);
  second.marker?.element?.fire('blur'); assertPreview(second, false);
});

test('card-to-marker focus transfer on one candidate survives the previous blur event', () => {
  const { view } = setup(); const candidate = item('a'); view.setCandidates([candidate]);
  candidate.card.fire('focus'); candidate.marker?.element?.fire('focus'); candidate.marker?.closeTooltip(); candidate.card.fire('blur');
  assertPreview(candidate, true);
  candidate.marker?.element?.fire('blur'); assertPreview(candidate, false);
});

test('replacing candidates removes old DOM/Leaflet listeners, preview classes and tooltips', () => {
  const { view } = setup(); const old = item('old'); const current = item('current'); view.setCandidates([old]);
  old.card.fire('mouseenter'); assertPreview(old, true); view.setCandidates([current]); assertPreview(old, false);
  for (const event of ['focus', 'blur', 'mouseenter', 'mouseleave']) assert.equal(old.card.listenerCount(event), 0);
  for (const event of ['focus', 'blur']) assert.equal(old.marker?.element?.listenerCount(event), 0);
  for (const event of ['mouseover', 'mouseout', 'tooltipopen']) assert.equal(old.marker?.listenerCount(event), 0);
  old.card.fire('mouseenter'); old.card.fire('focus'); old.marker?.fire('mouseover'); old.marker?.element?.fire('focus');
  assertPreview(old, false); assertPreview(current, false);
  current.card.fire('focus'); assertPreview(current, true);
});

test('repeated candidate replacement leaves exactly one binding for each event', () => {
  const { view } = setup(); const candidate = item('a');
  for (let iteration = 0; iteration < 5; iteration++) view.setCandidates([candidate]);
  for (const event of ['focus', 'blur', 'mouseenter', 'mouseleave']) assert.equal(candidate.card.listenerCount(event), 1);
  for (const event of ['focus', 'blur']) assert.equal(candidate.marker?.element?.listenerCount(event), 1);
  for (const event of ['mouseover', 'mouseout', 'tooltipopen']) assert.equal(candidate.marker?.listenerCount(event), 1);
  candidate.marker?.fire('mouseover'); assertPreview(candidate, true); assert.equal(candidate.marker?.tooltipOpenCalls, 1);
});

test('clearing results closes every old tooltip and prevents old focus from reappearing', () => {
  const { view, map, countLabel } = setup(); const first = item('a'); const second = item('b'); view.setCandidates([first, second]);
  first.card.fire('focus'); second.marker?.openTooltip(); view.setCandidates([]);
  assertPreview(first, false); assertPreview(second, false);
  first.card.fire('focus'); second.marker?.fire('mouseover'); map.fire('moveend');
  assertPreview(first, false); assertPreview(second, false); assert.equal(countLabel.textContent, '当前地图范围内 0 / 本次返回 0');
});

test('a marker without an attached DOM element still counts and supports pointer previews', () => {
  const { view, countLabel } = setup(); const candidate = item('detached'); candidate.marker = new FakeMarker({ x: 10, y: 10 }, null);
  view.setCandidates([candidate]); assert.equal(countLabel.textContent, '当前地图范围内 1 / 本次返回 1');
  candidate.marker.fire('mouseover'); assertPreview(candidate, true);
  view.setCandidates([]); assertPreview(candidate, false); assert.equal(candidate.marker.listenerCount('mouseover'), 0);
});

test('a native tooltip open on pointer B is suppressed while keyboard focus owns A', () => {
  const { view } = setup(); const first = item('a'); const second = item('b'); view.setCandidates([first, second]);
  first.card.fire('focus');
  second.marker?.openTooltip();
  assertPreview(first, true); assertPreview(second, false);
  second.marker?.fire('mouseover');
  assertPreview(first, true); assertPreview(second, false);
  first.card.fire('blur');
  assertPreview(first, false); assertPreview(second, true);
});

test('a focused marker restores its tooltip after Leaflet closes it on mouseout', () => {
  const { view } = setup(); const candidate = item('a'); view.setCandidates([candidate]);
  candidate.marker?.element?.fire('focus'); assertPreview(candidate, true);
  candidate.marker?.closeTooltip(); candidate.marker?.fire('mouseout');
  assertPreview(candidate, true);
  candidate.marker?.element?.fire('blur'); assertPreview(candidate, false);
});

test('re-registering a currently focused DOM node keeps its keyboard preview', () => {
  const { view } = setup(); const candidate = item('a');
  candidate.card.ownerDocument = { activeElement: candidate.card };
  view.setCandidates([candidate]); assertPreview(candidate, true);
  view.setCandidates([candidate, item('b')]); assertPreview(candidate, true);
});
