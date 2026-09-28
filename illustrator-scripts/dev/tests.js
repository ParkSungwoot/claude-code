'use strict';
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const { runScript, Driver } = require('./harness');

const BASE = path.join(__dirname, '..');
const S = {
  rename: path.join(BASE, 'scripts/BatchRename.jsx'),
  grid: path.join(BASE, 'scripts/GridArrange.jsx'),
  export: path.join(BASE, 'scripts/ExportArtboards.jsx'),
  template: path.join(BASE, 'template/UITemplate.jsx'),
  essential: path.join(BASE, 'scripts/COC_illust Essential.jsx'),
};
const TMP = path.join(__dirname, 'tmp');
fs.rmSync(TMP, { recursive: true, force: true });
fs.mkdirSync(TMP, { recursive: true });

const tests = [];
const test = (name, fn) => tests.push({ name, fn });

function run(script, config) {
  const env = runScript(script, Object.assign({ tmpBase: TMP }, config));
  if (env.thrown) throw env.thrown;
  for (const a of env.alerts) {
    if (/스크립트 실행 중 오류/.test(a.msg)) throw new Error('script reported error: ' + a.msg);
  }
  assert.deepStrictEqual(env.errors, [], 'strict mock violations');
  return env;
}

const near = (a, b, eps = 1e-6) => Math.abs(a - b) <= eps;
function assertBounds(actual, expected, label) {
  for (let i = 0; i < 4; i++) {
    if (!near(actual[i], expected[i], 1e-6)) {
      throw new Error(`${label}: bounds ${JSON.stringify(actual)} != ${JSON.stringify(expected)}`);
    }
  }
}
const status = (ui, re) => {
  const hits = ui.texts().filter((t) => re.test(t));
  assert.ok(hits.length, `no status matching ${re} in ${JSON.stringify(ui.texts())}`);
  return hits[0];
};
const MM = 72 / 25.4;
const rect = (name, l, t, w, h, extra) => Object.assign({ type: 'PathItem', name, bounds: [l, t, l + w, t - h] }, extra || {});
const text = (contents, l, t, extra) => Object.assign({ type: 'TextFrame', name: '', contents, bounds: [l, t, l + 20, t - 10] }, extra || {});

// ===========================================================================
//  BatchRename
// ===========================================================================
const threeBoards = [
  { name: 'Artboard 1', rect: [0, 0, 100, -100] },
  { name: 'Artboard 2', rect: [200, 0, 300, -100] },
  { name: 'Artboard 3', rect: [0, -200, 100, -300] },
];

test('rename: artboards with default pattern', () => {
  const env = run(S.rename, {
    documents: [{ name: 'poster.ai', artboards: threeBoards.map((a) => Object.assign({}, a)) }],
    driver(ui) {
      assert.strictEqual(ui.find('radiobutton', '대지 (3)')._state.value, true);
      assert.strictEqual(ui.after('패턴:', 'edittext').text, 'Page_{nn}');
      const lb = ui.all('listbox')[0];
      assert.deepStrictEqual(ui.listItems(lb), [
        'Artboard 1   →   Page_01', 'Artboard 2   →   Page_02', 'Artboard 3   →   Page_03']);
      status(ui, /^총 3개 중 3개가 바뀝니다/);
      ui.ok('적용');
    },
  });
  const doc = env.ai.documents[0];
  assert.deepStrictEqual(doc._artboards.map((a) => a.name), ['Page_01', 'Page_02', 'Page_03']);
});

test('rename: sort artboards by rows and by columns, reverse, start/step', () => {
  const boards = () => [
    { name: 'BR', rect: [200, -200, 300, -300] },
    { name: 'TL', rect: [0, 0, 100, -100] },
    { name: 'TR', rect: [200, 5, 300, -95] }, // slightly higher: same row within tolerance
    { name: 'BL', rect: [0, -200, 100, -300] },
  ];
  let env = run(S.rename, {
    documents: [{ artboards: boards() }],
    driver(ui) {
      ui.type(ui.after('패턴:', 'edittext'), '{name}-{n}');
      ui.select(ui.after('정렬:', 'dropdownlist'), 1);
      ui.ok('적용');
    },
  });
  assert.deepStrictEqual(env.ai.documents[0]._artboards.map((a) => a.name), ['BR-4', 'TL-1', 'TR-2', 'BL-3']);

  env = run(S.rename, {
    documents: [{ artboards: boards() }],
    driver(ui) {
      ui.type(ui.after('패턴:', 'edittext'), '{name}-{nn}');
      ui.select(ui.after('정렬:', 'dropdownlist'), 2);
      ui.click(ui.find('checkbox', '역순'));
      ui.type(ui.after('시작 번호:', 'edittext'), '10');
      ui.type(ui.after('증가:', 'edittext'), '-2');
      ui.ok('적용');
    },
  });
  // columns: TL, BL, TR, BR -> reversed: BR, TR, BL, TL -> 10, 08, 06, 04
  assert.deepStrictEqual(env.ai.documents[0]._artboards.map((a) => a.name), ['BR-10', 'TL-04', 'TR-08', 'BL-06']);
});

test('rename: literal find/replace keeps $ literally, case-insensitive', () => {
  const env = run(S.rename, {
    documents: [{ artboards: [{ name: 'Logo A', rect: [0, 0, 1, -1] }, { name: 'logo B', rect: [2, 0, 3, -1] }, { name: 'Icon', rect: [4, 0, 5, -1] }] }],
    driver(ui) {
      ui.click(ui.find('radiobutton', '찾아서 바꾸기'));
      ui.type(ui.after('찾기:', 'edittext'), 'LOGO');
      ui.type(ui.after('바꾸기:', 'edittext'), 'Mark$1-{nn}');
      status(ui, /^총 3개 중 2개가 바뀝니다/);
      ui.ok('적용');
    },
  });
  assert.deepStrictEqual(env.ai.documents[0]._artboards.map((a) => a.name), ['Mark$1-01 A', 'Mark$1-02 B', 'Icon']);
});

test('rename: regex with groups, case-sensitive option, invalid regex blocks apply', () => {
  const env = run(S.rename, {
    documents: [{ artboards: [{ name: 'Artboard 1', rect: [0, 0, 1, -1] }, { name: 'artboard 2', rect: [2, 0, 3, -1] }] }],
    driver(ui) {
      ui.click(ui.find('radiobutton', '찾아서 바꾸기'));
      ui.click(ui.find('checkbox', '정규식 사용'));
      const find = ui.after('찾기:', 'edittext');
      ui.type(find, '(');
      status(ui, /^확인 필요: 정규식이 올바르지 않습니다/);
      assert.strictEqual(ui.button('적용')._state.enabled, false);
      ui.type(find, '^Artboard (\\d+)$');
      ui.type(ui.after('바꾸기:', 'edittext'), 'P$1_{nnn}');
      ui.click(ui.find('checkbox', '대소문자 구분'));
      status(ui, /^총 2개 중 1개가 바뀝니다/);
      ui.ok('적용');
    },
  });
  assert.deepStrictEqual(env.ai.documents[0]._artboards.map((a) => a.name), ['P1_001', 'artboard 2']);
});

test('rename: number text frames in visual order, ignoring non-text items', () => {
  // 3 x 2 grid, selection order shuffled, plus a path that must be ignored
  const sel = [
    text('x', 60, -40), text('x', 0, 0), rect('shape', 500, 500, 10, 10), text('x', 30, 2),
    text('x', 0, -41), text('x', 60, 0), text('x', 30, -40),
  ];
  const env = run(S.rename, {
    documents: [{ selection: sel }],
    driver(ui) {
      ui.click(ui.find('radiobutton', '선택 텍스트 (6)'));
      assert.strictEqual(ui.after('패턴:', 'edittext').text, '{nnn}');
      ui.select(ui.after('정렬:', 'dropdownlist'), 1);
      ui.ok('적용');
    },
  });
  const items = env.ai.documents[0]._items;
  const got = items.map((it) => it._spec.contents);
  assert.deepStrictEqual(got, ['006', '001', undefined, '002', '004', '003', '005']);
});

test('rename: layers with and without sublayers; failures reported', () => {
  const layers = () => [
    { name: 'A', layers: [{ name: 'A1' }, { name: 'A2', lockedName: true }] },
    { name: 'B' },
  ];
  let env = run(S.rename, {
    documents: [{ layers: layers() }],
    driver(ui) {
      ui.click(ui.find('radiobutton', '레이어 (2)'));
      assert.strictEqual(ui.after('정렬:', 'dropdownlist')._state.enabled, false);
      ui.type(ui.after('패턴:', 'edittext'), 'L{n}');
      ui.ok('적용');
    },
  });
  let doc = env.ai.documents[0];
  assert.deepStrictEqual(Array.from(doc._layers).map((l) => l.name), ['L1', 'L2']);
  assert.strictEqual(env.alerts.length, 0);

  env = run(S.rename, {
    documents: [{ layers: layers() }],
    driver(ui) {
      ui.click(ui.find('radiobutton', '레이어 (2)'));
      ui.click(ui.find('checkbox', '하위 레이어도 포함'));
      ui.type(ui.after('패턴:', 'edittext'), 'L{n}');
      const lb = ui.all('listbox')[0];
      assert.deepStrictEqual(ui.listItems(lb), ['A   →   L1', '     A1   →   L2', '     A2   →   L3', 'B   →   L4']);
      ui.ok('적용');
    },
  });
  doc = env.ai.documents[0];
  assert.deepStrictEqual([doc._layers[0].name, doc._layers[0].layers[0].name, doc._layers[0].layers[1].name, doc._layers[1].name],
    ['L1', 'L2', 'A2', 'L4']);
  assert.strictEqual(env.alerts.length, 1);
  assert.match(env.alerts[0].msg, /3개를 바꿨지만 1개는 바꾸지 못했습니다/);
});

test('rename: empty result allowed for objects but not for artboards', () => {
  run(S.rename, {
    documents: [{ artboards: [{ name: 'X', rect: [0, 0, 1, -1] }] }],
    driver(ui) {
      ui.click(ui.find('radiobutton', '찾아서 바꾸기'));
      ui.type(ui.after('찾기:', 'edittext'), 'X');
      status(ui, /^확인 필요: 1번째 항목이 빈 이름이 됩니다/);
      assert.strictEqual(ui.button('적용')._state.enabled, false);
      ui.cancel();
    },
  });
  const env = run(S.rename, {
    documents: [{ selection: [rect('X', 0, 0, 1, 1), rect('', 5, 0, 1, 1)] }],
    driver(ui) {
      ui.click(ui.find('radiobutton', '선택 객체 (2)'));
      const lb = ui.all('listbox')[0];
      ui.click(ui.find('radiobutton', '찾아서 바꾸기'));
      ui.type(ui.after('찾기:', 'edittext'), 'X');
      assert.deepStrictEqual(ui.listItems(lb), ['X   →   (빈 이름)', '<패스>   →   (빈 이름)']);
      status(ui, /^총 2개 중 1개가 바뀝니다/);
      ui.ok('적용');
    },
  });
  assert.deepStrictEqual(env.ai.documents[0]._items.map((i) => i._spec.name), ['', '']);
});

test('rename: text editing disables selection targets; cancel changes nothing', () => {
  const env = run(S.rename, {
    documents: [{ textEditing: true, artboards: threeBoards.map((a) => Object.assign({}, a)) }],
    driver(ui) {
      assert.strictEqual(ui.find('radiobutton', '선택 객체 (0)')._state.enabled, false);
      assert.strictEqual(ui.find('radiobutton', '선택 텍스트 (0)')._state.enabled, false);
      status(ui, /텍스트 편집 중이라/);
      ui.cancel();
    },
  });
  assert.deepStrictEqual(env.ai.documents[0]._artboards.map((a) => a.name), ['Artboard 1', 'Artboard 2', 'Artboard 3']);
});

test('rename: settings and per-target patterns are remembered', () => {
  const root = fs.mkdtempSync(path.join(TMP, 'persist-'));
  run(S.rename, {
    root,
    documents: [{ selection: [rect('a', 0, 0, 1, 1)], layers: [{ name: 'A' }] }],
    driver(ui) {
      const pattern = ui.after('패턴:', 'edittext');
      ui.click(ui.find('radiobutton', '선택 객체 (1)'));
      assert.strictEqual(pattern.text, 'Item_{nn}');
      ui.type(pattern, 'Obj-{n}');
      ui.click(ui.find('radiobutton', '레이어 (1)'));
      assert.strictEqual(pattern.text, 'Layer_{nn}');
      ui.type(pattern, 'Layer-{nnn} ✓');
      ui.click(ui.find('radiobutton', '선택 객체 (1)'));
      assert.strictEqual(pattern.text, 'Obj-{n}');
      ui.click(ui.find('radiobutton', '레이어 (1)'));
      ui.click(ui.find('radiobutton', '찾아서 바꾸기'));
      ui.type(ui.after('찾기:', 'edittext'), 'a=b&c%');
      ui.click(ui.find('radiobutton', '새 이름 짓기 (패턴)'));
      ui.click(ui.find('checkbox', '역순'));
      ui.ok('적용');
    },
  });
  const ini = fs.readFileSync(path.join(root, 'userData/IllustratorUIScripts/BatchRename.ini'), 'utf8');
  assert.match(ini, /^target=layers$/m);
  run(S.rename, {
    root,
    documents: [{ selection: [rect('a', 0, 0, 1, 1)], layers: [{ name: 'A' }] }],
    driver(ui) {
      assert.strictEqual(ui.find('radiobutton', '레이어 (1)')._state.value, true);
      assert.strictEqual(ui.after('패턴:', 'edittext').text, 'Layer-{nnn} ✓');
      assert.strictEqual(ui.after('찾기:', 'edittext').text, 'a=b&c%');
      assert.strictEqual(ui.find('checkbox', '역순')._state.value, true);
      ui.click(ui.find('radiobutton', '선택 객체 (1)'));
      assert.strictEqual(ui.after('패턴:', 'edittext').text, 'Obj-{n}');
      ui.cancel();
    },
  });
});

test('rename: saved target without items falls back to artboards', () => {
  const root = fs.mkdtempSync(path.join(TMP, 'fallback-'));
  fs.mkdirSync(path.join(root, 'userData/IllustratorUIScripts'), { recursive: true });
  fs.writeFileSync(path.join(root, 'userData/IllustratorUIScripts/BatchRename.ini'), 'target=texts\nsortMode=7\nbogus=1\nstart=%E0%A4%A');
  run(S.rename, {
    root,
    documents: [{}],
    driver(ui) {
      assert.strictEqual(ui.find('radiobutton', '대지 (1)')._state.value, true);
      assert.strictEqual(ui.after('정렬:', 'dropdownlist').selection.index, 0);
      assert.strictEqual(ui.after('시작 번호:', 'edittext').text, '1');
      ui.cancel();
    },
  });
});

test('rename: preview list is capped at 200 lines', () => {
  const boards = [];
  for (let i = 0; i < 250; i++) boards.push({ name: 'A' + i, rect: [i * 10, 0, i * 10 + 5, -5] });
  const env = run(S.rename, {
    documents: [{ artboards: boards }],
    driver(ui) {
      const items = ui.listItems(ui.all('listbox')[0]);
      assert.strictEqual(items.length, 201);
      assert.strictEqual(items[200], '... 외 50개');
      ui.ok('적용');
    },
  });
  assert.strictEqual(env.ai.documents[0]._artboards[249].name, 'Page_250');
});

test('rename: invalid numbers block apply; no documents shows alert', () => {
  run(S.rename, {
    documents: [{}],
    driver(ui) {
      ui.type(ui.after('시작 번호:', 'edittext'), '1.5');
      status(ui, /^확인 필요: 시작 번호와 증가 값은 정수로/);
      assert.strictEqual(ui.button('적용')._state.enabled, false);
      ui.cancel();
    },
  });
  const env = run(S.rename, { documents: [] });
  assert.match(env.alerts[0].msg, /열려 있는 문서가 없습니다/);
});

// ===========================================================================
//  GridArrange
// ===========================================================================
function gridItems() {
  // 2 rows x 3 columns of 10x10 squares, selection order shuffled
  return [
    rect('B2', 30, -40, 10, 10), rect('A1', 0, 0, 10, 10), rect('A3', 60, 0, 10, 10),
    rect('B1', 0, -40, 10, 10), rect('A2', 30, 1, 10, 10), rect('B3', 60, -40, 10, 10),
  ];
}
const byName = (doc) => {
  const out = {};
  for (const it of doc._items) out[it._spec.name] = it._spec.bounds;
  return out;
};

test('grid: 3 columns, 5 mm gap, centered, position order', () => {
  const g = 10 + 5 * MM;
  const env = run(S.grid, {
    documents: [{ selection: gridItems() }],
    driver(ui) {
      const cols = ui.after('열 수:', 'edittext');
      assert.strictEqual(cols.text, '3'); // ceil(sqrt(6))
      ui.click(ui.find('checkbox', '미리보기')); // turn preview off
      status(ui, /^객체 6개를 3열 × 2행으로 배치합니다/);
      ui.ok('정렬');
    },
  });
  const b = byName(env.ai.documents[0]);
  // origin = left 0, top 1 (A2 is 1pt higher)
  assertBounds(b.A1, [0, 1, 10, -9], 'A1');
  assertBounds(b.A2, [g, 1, g + 10, -9], 'A2');
  assertBounds(b.A3, [2 * g, 1, 2 * g + 10, -9], 'A3');
  assertBounds(b.B1, [0, 1 - g, 10, 1 - g - 10], 'B1');
  assertBounds(b.B3, [2 * g, 1 - g, 2 * g + 10, 1 - g - 10], 'B3');
});

test('grid: preview then cancel restores exact positions', () => {
  const original = gridItems().map((i) => i.bounds.slice());
  const env = run(S.grid, {
    documents: [{ selection: gridItems() }],
    driver(ui) {
      assert.ok(ui.env.translateCalls.length > 0, 'preview should move items when dialog opens');
      ui.type(ui.after('열 수:', 'edittext'), '2');
      ui.type(ui.after('가로:', 'edittext'), '12.5');
      ui.select(ui.after('칸 크기:', 'dropdownlist'), 1);
      ui.cancel();
    },
  });
  env.ai.documents[0]._items.forEach((it, i) => assertBounds(it._spec.bounds, original[i], 'item ' + i));
  assert.ok(env.counts.redraw >= 3);
});

test('grid: preview then OK restores first, then applies once', () => {
  let marker = 0;
  const g = 10 + 5 * MM;
  const env = run(S.grid, {
    documents: [{ selection: gridItems() }],
    driver(ui) {
      ui.type(ui.after('열 수:', 'edittext'), '2');
      ui.type(ui.after('열 수:', 'edittext'), '6');
      marker = ui.env.translateCalls.length;
      ui.ok('정렬');
    },
  });
  const after = env.translateCalls.slice(marker);
  const before = env.translateCalls.slice(0, marker);
  // every moved item is first moved back by its whole preview offset, then moved once more by the same offset
  const names = [...new Set(before.map((c) => c.name))];
  assert.strictEqual(after.length, names.length * 2);
  for (const n of names) {
    const total = before.filter((c) => c.name === n).reduce((a, c) => [a[0] + c.dx, a[1] + c.dy], [0, 0]);
    const calls = after.filter((c) => c.name === n);
    assert.strictEqual(calls.length, 2, n);
    assert.ok(near(calls[0].dx, -total[0]) && near(calls[0].dy, -total[1]), 'restore ' + n);
    assert.ok(near(calls[1].dx, total[0]) && near(calls[1].dy, total[1]), 'apply ' + n);
  }
  const restoreIdx = names.map((n) => after.findIndex((c) => c.name === n));
  const applyIdx = names.map((n) => after.map((c, i) => (c.name === n ? i : -1)).filter((i) => i >= 0)[1]);
  assert.ok(Math.max(...restoreIdx) < Math.min(...applyIdx), 'all restores happen before any final move');
  const b = byName(env.ai.documents[0]);
  assertBounds(b.B1, [3 * g, 1, 3 * g + 10, -9], 'B1 (single row, 4th)');
});

test('grid: column direction, compact cells, right/bottom, selection order, pt units', () => {
  const sel = [
    rect('P1', 0, 100, 10, 20), rect('P2', 50, 100, 30, 10), rect('P3', 100, 100, 20, 20),
    rect('P4', 0, 50, 10, 10), rect('P5', 50, 50, 40, 5),
  ];
  const env = run(S.grid, {
    documents: [{ selection: sel }],
    driver(ui) {
      ui.click(ui.find('checkbox', '미리보기'));
      ui.type(ui.after('열 수:', 'edittext'), '2');
      ui.select(ui.after('채우는 방향:', 'dropdownlist'), 1);
      ui.select(ui.after('칸 크기:', 'dropdownlist'), 1);
      ui.select(ui.after('가로 정렬:', 'dropdownlist'), 2);
      ui.select(ui.after('  세로 정렬:', 'dropdownlist'), 2);
      ui.select(ui.after('순서:', 'dropdownlist'), 2);
      const unit = ui.all('dropdownlist').find((d) => d._state._items.some((i) => i.text === 'pt'));
      ui.select(unit, 2);
      ui.type(ui.after('가로:', 'edittext'), '2');
      ui.type(ui.after('세로:', 'edittext'), '3');
      status(ui, /2열 × 3행/);
      ui.ok('정렬');
    },
  });
  const b = byName(env.ai.documents[0]);
  assertBounds(b.P1, [20, 100, 30, 80], 'P1');
  assertBounds(b.P2, [0, 77, 30, 67], 'P2');
  assertBounds(b.P3, [10, 64, 30, 44], 'P3');
  assertBounds(b.P4, [62, 90, 72, 80], 'P4');
  assertBounds(b.P5, [32, 72, 72, 67], 'P5');
});

test('grid: clipping groups use the mask bounds', () => {
  const group = {
    type: 'GroupItem', name: 'clip', clipped: true, bounds: [0, 100, 200, -100],
    children: [
      { type: 'PathItem', name: 'mask', clipping: true, bounds: [50, 50, 70, 30] },
      { type: 'PathItem', name: 'hidden art', bounds: [0, 100, 200, -100] },
    ],
  };
  const env = run(S.grid, {
    documents: [{ selection: [group, rect('P', 300, 50, 20, 20)] }],
    driver(ui) {
      ui.click(ui.find('checkbox', '미리보기'));
      ui.type(ui.after('열 수:', 'edittext'), '2');
      const unit = ui.all('dropdownlist').find((d) => d._state._items.some((i) => i.text === 'pt'));
      ui.select(unit, 2);
      ui.type(ui.after('가로:', 'edittext'), '0');
      ui.select(ui.after('순서:', 'dropdownlist'), 2);
      ui.ok('정렬');
    },
  });
  const b = byName(env.ai.documents[0]);
  assertBounds(b.P, [70, 50, 90, 30], 'P next to the mask, not the hidden art');
  assertBounds(b.clip, [0, 100, 200, -100], 'group did not move');
});

test('grid: unit switch converts gap values; stroke option uses visible bounds', () => {
  const sel = [rect('a', 0, 0, 10, 10, { stroke: 2 }), rect('b', 50, 0, 10, 10, { stroke: 2 })];
  const env = run(S.grid, {
    documents: [{ selection: sel }],
    driver(ui) {
      ui.click(ui.find('checkbox', '미리보기'));
      const gapX = ui.after('가로:', 'edittext');
      const unit = ui.all('dropdownlist').find((d) => d._state._items.some((i) => i.text === 'pt'));
      assert.strictEqual(unit.selection.text, 'mm');
      ui.select(unit, 2);
      assert.strictEqual(gapX.text, '14.173');
      ui.select(unit, 4);
      assert.strictEqual(gapX.text, '0.197');
      ui.select(unit, 2);
      ui.type(gapX, '4');
      ui.type(ui.after('열 수:', 'edittext'), '2');
      ui.ok('정렬');
    },
  });
  const b = byName(env.ai.documents[0]);
  // visible width = 12 (stroke 2), gap 4 -> b.visibleLeft = a.visibleLeft + 16
  assertBounds(b.a, [0, 0, 10, -10], 'a');
  assertBounds(b.b, [16, 0, 26, -10], 'b');
});

test('grid: natural name order, reverse, and pattern flag follows preference', () => {
  const sel = [rect('Item10', 0, 0, 10, 10), rect('Item2', 20, 0, 10, 10), rect('Item1', 40, 0, 10, 10)];
  const env = run(S.grid, {
    prefs: { includeStrokeInBounds: false, transformPatterns: true },
    documents: [{ selection: sel }],
    driver(ui) {
      ui.click(ui.find('checkbox', '미리보기'));
      assert.strictEqual(ui.find('checkbox', '선 두께까지 포함한 크기로 계산')._state.value, false);
      ui.type(ui.after('열 수:', 'edittext'), '3');
      ui.select(ui.after('순서:', 'dropdownlist'), 3);
      ui.click(ui.find('checkbox', '역순'));
      const unit = ui.all('dropdownlist').find((d) => d._state._items.some((i) => i.text === 'pt'));
      ui.select(unit, 2);
      ui.type(ui.after('가로:', 'edittext'), '0');
      ui.ok('정렬');
    },
  });
  const b = byName(env.ai.documents[0]);
  assertBounds(b.Item10, [0, 0, 10, -10], 'Item10 first (reversed)');
  assertBounds(b.Item2, [10, 0, 20, -10], 'Item2');
  assertBounds(b.Item1, [20, 0, 30, -10], 'Item1');
  for (const c of env.translateCalls) assert.deepStrictEqual(c.flags, [true, true, true, true]);
});

test('grid: default pattern flag off; invalid input disables OK; locked items reported', () => {
  const sel = [rect('a', 0, 0, 10, 10), rect('b', 50, 0, 10, 10, { locked: true })];
  const env = run(S.grid, {
    documents: [{ selection: sel }],
    driver(ui) {
      const cols = ui.after('열 수:', 'edittext');
      ui.type(cols, '0');
      status(ui, /^확인 필요: 열 수는 1~1000/);
      assert.strictEqual(ui.button('정렬')._state.enabled, false);
      ui.type(cols, '1');
      ui.type(ui.after('세로:', 'edittext'), 'abc');
      status(ui, /^확인 필요: 간격은 숫자로/);
      ui.type(ui.after('세로:', 'edittext'), '0');
      status(ui, /1개는 옮길 수 없음/);
      ui.ok('정렬');
    },
  });
  assert.match(env.alerts[0].msg, /1개 객체는 옮기지 못했습니다/);
  for (const c of env.translateCalls) assert.deepStrictEqual(c.flags, [true, false, true, false]);
});

test('grid: requires 2+ items and no text editing', () => {
  let env = run(S.grid, { documents: [{ selection: [rect('a', 0, 0, 1, 1)] }] });
  assert.match(env.alerts[0].msg, /2개 이상 선택/);
  env = run(S.grid, { documents: [{ textEditing: true }] });
  assert.match(env.alerts[0].msg, /텍스트를 편집하는 중/);
  env = run(S.grid, { documents: [] });
  assert.match(env.alerts[0].msg, /열려 있는 문서가 없습니다/);
});

test('grid: settings are remembered (unit, gaps, options)', () => {
  const root = fs.mkdtempSync(path.join(TMP, 'grid-persist-'));
  run(S.grid, {
    root,
    documents: [{ selection: gridItems(), rulerUnits: 8 }],
    driver(ui) {
      const unit = ui.all('dropdownlist').find((d) => d._state._items.some((i) => i.text === 'pt'));
      assert.strictEqual(unit.selection.text, 'px'); // from ruler units
      ui.type(ui.after('가로:', 'edittext'), '7');
      ui.type(ui.after('열 수:', 'edittext'), '4');
      ui.click(ui.find('checkbox', '미리보기'));
      ui.ok('정렬');
    },
  });
  run(S.grid, {
    root,
    documents: [{ selection: gridItems() }],
    driver(ui) {
      const unit = ui.all('dropdownlist').find((d) => d._state._items.some((i) => i.text === 'pt'));
      assert.strictEqual(unit.selection.text, 'px');
      assert.strictEqual(ui.after('가로:', 'edittext').text, '7');
      assert.strictEqual(ui.after('열 수:', 'edittext').text, '4');
      assert.strictEqual(ui.find('checkbox', '미리보기')._state.value, false);
      ui.cancel();
    },
  });
});

// ===========================================================================
//  ExportArtboards
// ===========================================================================
const exportDoc = (extra) => Object.assign({
  file: 'work/poster.ai',
  activeArtboard: 1,
  artboards: [
    { name: 'Cover', rect: [0, 0, 100, -100] },
    { name: 'Page 2', rect: [200, 0, 300, -100] },
    { name: '표지', rect: [400, 0, 500, -100] },
  ],
}, extra || {});
const readRecord = (p) => JSON.parse(fs.readFileSync(p, 'utf8'));
const listDir = (p) => (fs.existsSync(p) ? fs.readdirSync(p).sort() : []);

test('export: PNG, all artboards, next to the document', () => {
  const env = run(S.export, {
    documents: [exportDoc()],
    driver(ui) {
      assert.strictEqual(ui.find('radiobutton', /^열린 문서 모두/)._state.enabled, false);
      status(ui, /^예: poster_Cover\.png$/);
      status(ui, /^대지 3개를 PNG 파일로 내보냅니다/);
      ui.ok('내보내기');
    },
  });
  const out = path.join(env.root, 'work');
  assert.deepStrictEqual(listDir(out), ['poster.ai', 'poster_Cover.png', 'poster_Page 2.png', 'poster_표지.png']);
  const rec = readRecord(path.join(out, 'poster_Page 2.png'));
  assert.strictEqual(rec.type, 'PNG24');
  assert.strictEqual(rec.artboard, 1);
  assert.strictEqual(rec.options.artBoardClipping, true);
  assert.strictEqual(rec.options.transparency, true);
  assert.ok(near(rec.options.horizontalScale, 150 / 72 * 100));
  const doc = env.ai.documents[0];
  assert.strictEqual(doc._activeArtboard, 1, 'active artboard restored');
  assert.strictEqual(env.ai.app.userInteractionLevel, 2, 'interaction level restored');
  assert.deepStrictEqual(listDir(path.join(env.root, 'temp')), [], 'temp folders removed');
  assert.match(env.alerts[0].msg, /^3개 파일을 내보냈습니다\.\n저장 위치: .*\/work$/);
  assert.deepStrictEqual(env.executed, [out]);
});

test('export: JPG range, quality, ppi, numbered pattern', () => {
  const env = run(S.export, {
    documents: [exportDoc()],
    driver(ui) {
      ui.select(ui.after('형식:', 'dropdownlist'), 1);
      ui.click(ui.find('radiobutton', '범위:'));
      ui.type(ui.after('범위:', 'edittext'), '3, 1');
      ui.type(ui.after('해상도:', 'edittext'), '300');
      ui.slide(ui.all('slider')[0], 55.4);
      ui.type(ui.after('이름 규칙:', 'edittext'), '{nn}_{artboard}');
      status(ui, /^예: 01_Cover\.jpg$/);
      ui.click(ui.find('checkbox', '끝나면 폴더 열기'));
      ui.ok('내보내기');
    },
  });
  const out = path.join(env.root, 'work');
  assert.deepStrictEqual(listDir(out), ['01_Cover.jpg', '03_표지.jpg', 'poster.ai']);
  const rec = readRecord(path.join(out, '03_표지.jpg'));
  assert.strictEqual(rec.type, 'JPEG');
  assert.strictEqual(rec.artboard, 2);
  assert.strictEqual(rec.options.qualitySetting, 55);
  assert.ok(near(rec.options.verticalScale, 300 / 72 * 100));
  assert.deepStrictEqual(env.executed, []);
});

test('export: SVG with outlined text ignores the ppi field', () => {
  const env = run(S.export, {
    documents: [exportDoc()],
    driver(ui) {
      const ppi = ui.after('해상도:', 'edittext');
      ui.type(ppi, '9999');
      status(ui, /^확인 필요: 해상도는 1~558/);
      ui.select(ui.after('형식:', 'dropdownlist'), 2);
      assert.strictEqual(ui.isUsable(ppi), false);
      ui.click(ui.find('checkbox', /^텍스트를 윤곽선으로/));
      ui.click(ui.find('radiobutton', '현재 대지만'));
      status(ui, /^대지 1개를 SVG 파일로/);
      ui.ok('내보내기');
    },
  });
  const out = path.join(env.root, 'work');
  assert.deepStrictEqual(listDir(out), ['poster.ai', 'poster_Page 2.svg']);
  const rec = readRecord(path.join(out, 'poster_Page 2.svg'));
  assert.strictEqual(rec.type, 'WOSVG');
  assert.strictEqual(rec.artboard, 1);
  assert.strictEqual(rec.options.saveMultipleArtboards, true);
  assert.strictEqual(rec.options.artboardRange, '2');
  assert.strictEqual(rec.options.fontType, 3);
  assert.strictEqual(rec.options.rasterImageLocation, 0);
});

test('export: PDF via Export for Screens with chosen preset', () => {
  const env = run(S.export, {
    documents: [exportDoc()],
    driver(ui) {
      ui.select(ui.after('형식:', 'dropdownlist'), 3);
      const preset = ui.after('사전 설정:', 'dropdownlist');
      assert.strictEqual(preset.selection.text, '[High Quality Print]');
      ui.select(preset, 2);
      ui.ok('내보내기');
    },
  });
  const out = path.join(env.root, 'work');
  assert.deepStrictEqual(listDir(out), ['poster.ai', 'poster_Cover.pdf', 'poster_Page 2.pdf', 'poster_표지.pdf']);
  const rec = readRecord(path.join(out, 'poster_표지.pdf'));
  assert.strictEqual(rec.method, 'exportForScreens');
  assert.strictEqual(rec.artboard, 2);
  assert.strictEqual(rec.options.pdfPreset, '[Smallest File Size]');
});

test('export: PDF hidden before CC 2018; Korean preset default', () => {
  run(S.export, {
    version: '21.1.0',
    documents: [exportDoc()],
    driver(ui) {
      assert.deepStrictEqual(ui.listItems(ui.after('형식:', 'dropdownlist')), ['PNG', 'JPG', 'SVG']);
      ui.cancel();
    },
  });
  run(S.export, {
    pdfPresets: ['[Illustrator 기본값]', '[고품질 인쇄]', '[최소 파일 크기]'],
    documents: [exportDoc()],
    driver(ui) {
      ui.select(ui.after('형식:', 'dropdownlist'), 3);
      assert.strictEqual(ui.after('사전 설정:', 'dropdownlist').selection.text, '[고품질 인쇄]');
      ui.cancel();
    },
  });
  run(S.export, {
    pdfPresetsThrows: true,
    documents: [exportDoc()],
    driver(ui) {
      ui.select(ui.after('형식:', 'dropdownlist'), 3);
      assert.strictEqual(ui.after('사전 설정:', 'dropdownlist').selection.text, '(기본값)');
      ui.cancel();
    },
  });
});

test('export: name collisions without and with overwrite', () => {
  const docSpec = () => exportDoc({
    artboards: [{ name: 'Same', rect: [0, 0, 1, -1] }, { name: 'same', rect: [2, 0, 3, -1] }, { name: 'Other', rect: [4, 0, 5, -1] }],
  });
  let env = run(S.export, {
    setup(e) {
      fs.mkdirSync(path.join(e.root, 'work'), { recursive: true });
      fs.writeFileSync(path.join(e.root, 'work/poster_Same.png'), 'existing');
    },
    documents: [docSpec()],
    driver(ui) { ui.ok('내보내기'); },
  });
  let out = path.join(env.root, 'work');
  assert.deepStrictEqual(listDir(out), ['poster.ai', 'poster_Other.png', 'poster_Same.png', 'poster_Same_2.png', 'poster_same_3.png']);
  // (case-insensitive disk: 'poster_same.png' would clash with the existing 'poster_Same.png')
  assert.strictEqual(fs.readFileSync(path.join(out, 'poster_Same.png'), 'utf8'), 'existing');

  env = run(S.export, {
    setup(e) {
      fs.mkdirSync(path.join(e.root, 'work'), { recursive: true });
      fs.writeFileSync(path.join(e.root, 'work/poster_Same.png'), 'existing');
    },
    documents: [docSpec()],
    driver(ui) {
      ui.click(ui.find('checkbox', '같은 이름의 파일 덮어쓰기'));
      ui.ok('내보내기');
    },
  });
  out = path.join(env.root, 'work');
  assert.deepStrictEqual(listDir(out), ['poster.ai', 'poster_Other.png', 'poster_Same.png', 'poster_same_2.png']);
  assert.notStrictEqual(fs.readFileSync(path.join(out, 'poster_Same.png'), 'utf8'), 'existing');
});

test('export: unsafe characters, trailing dots, percent signs survive', () => {
  const env = run(S.export, {
    documents: [exportDoc({ artboards: [
      { name: 'a/b:c*?', rect: [0, 0, 1, -1] },
      { name: ' trailing. ', rect: [2, 0, 3, -1] },
      { name: '표지 100%A1', rect: [4, 0, 5, -1] },
    ] })],
    driver(ui) {
      ui.type(ui.after('이름 규칙:', 'edittext'), '{artboard}');
      ui.ok('내보내기');
    },
  });
  assert.deepStrictEqual(listDir(path.join(env.root, 'work')), ['a_b_c__.png', 'poster.ai', 'trailing.png', '표지 100%A1.png']);
});

test('export: all open documents, unsaved one goes to chosen folder, state restored', () => {
  const env = run(S.export, {
    documents: [
      { file: 'w1/a.ai', activeArtboard: 1, artboards: [{ name: 'X', rect: [0, 0, 1, -1] }, { name: 'Y', rect: [2, 0, 3, -1] }] },
      { name: 'Untitled-2', active: true, artboards: [{ name: 'Z', rect: [0, 0, 1, -1] }] },
    ],
    driver(ui) {
      ui.click(ui.find('radiobutton', '열린 문서 모두 (2개)'));
      status(ui, /^예: a_X\.png$/);
      ui.ok('내보내기');
    },
  });
  assert.deepStrictEqual(listDir(path.join(env.root, 'w1')), ['a.ai', 'a_X.png', 'a_Y.png']);
  assert.deepStrictEqual(listDir(path.join(env.root, 'home/Desktop')), ['Untitled-2_Z.png']);
  assert.strictEqual(env.ai.app.activeDocument.name, 'Untitled-2');
  assert.strictEqual(env.ai.documents[0]._activeArtboard, 1);
  assert.match(env.alerts[0].msg, /3개 파일을 내보냈습니다/);
  assert.strictEqual((env.alerts[0].msg.match(/저장 위치:/g) || []).length, 2);
});

test('export: range validation messages', () => {
  run(S.export, {
    documents: [exportDoc()],
    driver(ui) {
      ui.click(ui.find('radiobutton', '범위:'));
      const range = ui.after('범위:', 'edittext');
      ui.type(range, 'abc');
      status(ui, /^확인 필요: 범위를 "1-3, 5" 처럼/);
      assert.strictEqual(ui.button('내보내기')._state.enabled, false);
      ui.type(range, '9-12');
      status(ui, /^확인 필요: 내보낼 대지가 없습니다/);
      ui.type(range, ' 2 ~ 3 ,, ');
      status(ui, /^대지 2개를/);
      ui.type(range, '');
      status(ui, /^확인 필요: 범위를/);
      ui.cancel();
    },
  });
});

test('export: choose folder, remembered next time', () => {
  const root = fs.mkdtempSync(path.join(TMP, 'export-persist-'));
  fs.mkdirSync(path.join(root, 'out dir'), { recursive: true });
  const env = run(S.export, {
    root,
    pickFolder: path.join(root, 'out dir'),
    documents: [exportDoc()],
    driver(ui) {
      ui.click(ui.button('폴더 선택...'));
      assert.strictEqual(ui.find('radiobutton', '아래 폴더')._state.value, true);
      status(ui, new RegExp('out dir$'));
      ui.select(ui.after('형식:', 'dropdownlist'), 1);
      ui.ok('내보내기');
    },
  });
  assert.deepStrictEqual(listDir(path.join(root, 'out dir')), ['poster_Cover.jpg', 'poster_Page 2.jpg', 'poster_표지.jpg']);
  assert.strictEqual(env.dialogs[0].kind, 'selectDlg');
  run(S.export, {
    root,
    documents: [exportDoc()],
    driver(ui) {
      assert.strictEqual(ui.find('radiobutton', '아래 폴더')._state.value, true);
      assert.strictEqual(ui.after('형식:', 'dropdownlist').selection.text, 'JPG');
      status(ui, new RegExp('out dir$'));
      ui.cancel();
    },
  });
});

test('export: one failure is reported, others still exported', () => {
  const env = run(S.export, {
    failExportFor: (rec) => rec.artboard === 1,
    documents: [exportDoc()],
    driver(ui) { ui.ok('내보내기'); },
  });
  assert.deepStrictEqual(listDir(path.join(env.root, 'work')), ['poster.ai', 'poster_Cover.png', 'poster_표지.png']);
  assert.match(env.alerts[0].msg, /2개 파일을 내보냈습니다\.\n1개는 내보내지 못했습니다\.\nposter_Page 2\.png : simulated export failure/);
  assert.strictEqual(env.alerts[0].errorIcon, true);
  assert.deepStrictEqual(listDir(path.join(env.root, 'temp')), []);
});

test('export: unsaved document whose fullName throws falls back to Desktop', () => {
  const env = run(S.export, {
    unsavedFullNameThrows: true,
    documents: [{ name: 'Untitled-1', artboards: [{ name: 'A', rect: [0, 0, 1, -1] }] }],
    driver(ui) { ui.ok('내보내기'); },
  });
  assert.deepStrictEqual(listDir(path.join(env.root, 'home/Desktop')), ['Untitled-1_A.png']);
});

// ===========================================================================
//  Template
// ===========================================================================
test('template: preview, then OK moves once (10 mm right, 5 mm down)', () => {
  const env = run(S.template, {
    documents: [{ selection: [rect('a', 0, 0, 10, 10), rect('b', 50, 0, 10, 10)] }],
    driver(ui) {
      ui.type(ui.after('세로 (↓ 아래쪽 +):', 'edittext'), '5');
      ui.type(ui.after('가로 (→ 오른쪽 +):', 'edittext'), '10');
      ui.ok('이동');
    },
  });
  const b = byName(env.ai.documents[0]);
  assertBounds(b.a, [10 * MM, -5 * MM, 10 * MM + 10, -5 * MM - 10], 'a');
  assertBounds(b.b, [50 + 10 * MM, -5 * MM, 60 + 10 * MM, -5 * MM - 10], 'b');
});

test('template: cancel restores, bad number blocks OK, empty selection alerts', () => {
  const env = run(S.template, {
    documents: [{ selection: [rect('a', 0, 0, 10, 10)] }],
    driver(ui) {
      ui.type(ui.after('가로 (→ 오른쪽 +):', 'edittext'), 'x');
      assert.strictEqual(ui.button('이동')._state.enabled, false);
      ui.type(ui.after('가로 (→ 오른쪽 +):', 'edittext'), '3,5');
      ui.cancel();
    },
  });
  assertBounds(byName(env.ai.documents[0]).a, [0, 0, 10, -10], 'a restored');
  const env2 = run(S.template, { documents: [{ selection: [] }] });
  assert.match(env2.alerts[0].msg, /객체를 먼저 선택해 주세요/);
});

// ===========================================================================
//  COC_illust Essential (palette + BridgeTalk)
// ===========================================================================
function openPanel(config) {
  const env = run(S.essential, config);
  assert.deepStrictEqual(env.tempLeaks(), [], 'temporary copies left in the document');
  const palettes = env.ui.windows.filter((w) => w._state.type === 'palette');
  assert.strictEqual(palettes.length, 1, 'one palette');
  return { env, ui: new Driver(palettes[0], env), win: palettes[0] };
}
const panelStatus = (ui) => ui.all('statictext').pop()._state.text;
const ptext = (name, anchor, paras, extra) => ({
  type: 'TextFrame', name, contents: 'text', bounds: [0, 0, 0, 0],
  text: Object.assign({ kind: 'point', orientation: 'h', rotation: 0, anchor, leading: 12, ascent: 9, descent: 3,
    paragraphs: paras.map((p) => (p.empty ? { width: 0, justification: 'LEFT', empty: true } : { width: p[0], justification: p[1] })) }, extra || {}),
});
const boxText = (name, kind, frame, paras) => ({
  type: 'TextFrame', name, contents: 'text', bounds: frame.slice(),
  text: { kind, frame, paragraphs: paras.map((p) => ({ width: p[0], justification: p[1] })) },
});
const specOf = (env, name) => env.ai.documents[0]._items.find((i) => i._spec.name === name)._spec;
const liveBounds = (env, name) => Array.from(env.ai.documents[0]._items.find((i) => i._spec.name === name).geometricBounds);

test('essential: opens as a palette once; running again reuses it', () => {
  const { env, win } = openPanel({ documents: [{}] });
  assert.strictEqual(env.counts.dialogsShown, 0);
  assert.strictEqual(win._state.type, 'palette');
  env.rerun();
  assert.strictEqual(env.ui.windows.length, 1, 'no second palette');
  win.close();
  env.rerun();
  assert.strictEqual(env.ui.windows.length, 2, 'new palette after closing the old one');
});

test('essential: horizontal equal gaps keep both ends, any selection order', () => {
  const g = (170 - 75) / 3;
  const { env, ui } = openPanel({
    documents: [{ selection: [rect('C', 100, 0, 5, 10), rect('A', 0, 0, 10, 10), rect('D', 150, -3, 20, 10), rect('B', 30, 5, 40, 20)] }],
  });
  ui.click(ui.button('가로 간격 같게'));
  assertBounds(specOf(env, 'A').bounds, [0, 0, 10, -10], 'A');
  assertBounds(specOf(env, 'B').bounds, [10 + g, 5, 50 + g, -15], 'B');
  assertBounds(specOf(env, 'C').bounds, [50 + 2 * g, 0, 55 + 2 * g, -10], 'C');
  assertBounds(specOf(env, 'D').bounds, [150, -3, 170, -13], 'D');
  assert.strictEqual(panelStatus(ui), '가로 4개를 간격 11.171 mm로 배열했습니다.');
  for (const c of env.translateCalls) assert.deepStrictEqual(c.flags, [true, false, true, false]);
  assert.ok(env.bridgeBodies.length === 1 && /^\(function cocEssentialCore\(req\)/.test(env.bridgeBodies[0]));
});

test('essential: vertical equal gaps (top to bottom)', () => {
  const { env, ui } = openPanel({
    documents: [{ selection: [rect('R', 2, -100, 10, 5), rect('P', 0, 0, 10, 10), rect('Q', 5, -30, 10, 30)] }],
  });
  ui.click(ui.button('세로 간격 같게'));
  assertBounds(specOf(env, 'P').bounds, [0, 0, 10, -10], 'P');
  assertBounds(specOf(env, 'Q').bounds, [5, -40, 15, -70], 'Q');
  assertBounds(specOf(env, 'R').bounds, [2, -100, 12, -105], 'R');
  assert.strictEqual(panelStatus(ui), '세로 3개를 간격 10.583 mm로 배열했습니다.');
});

test('essential: fixed gap in mm with start / center / end anchors', () => {
  const gap = 5 * MM;
  const items = () => [rect('A', 0, 0, 10, 10), rect('B', 50, 0, 20, 10), rect('C', 100, 0, 30, 10)];
  const length = 60 + 2 * gap;
  const cases = [[0, 0], [1, (130 - length) / 2], [2, 130 - length]];
  for (const [anchorIndex, startPos] of cases) {
    const { env, ui } = openPanel({ documents: [{ selection: items() }] });
    ui.click(ui.find('radiobutton', '직접 입력'));
    ui.type(ui.after('간격:', 'edittext'), '5');
    ui.select(ui.after('기준:', 'dropdownlist'), anchorIndex);
    ui.click(ui.button('가로 간격 같게'));
    assert.ok(near(specOf(env, 'A').bounds[0], startPos), 'A at ' + startPos);
    assert.ok(near(specOf(env, 'B').bounds[0], startPos + 10 + gap), 'B');
    assert.ok(near(specOf(env, 'C').bounds[0], startPos + 30 + 2 * gap), 'C');
    assert.strictEqual(panelStatus(ui), '가로 3개를 간격 5 mm로 배열했습니다.');
  }
});

test('essential: too few objects, invalid gap, no document, text editing', () => {
  let { env, ui } = openPanel({ documents: [{ selection: [rect('A', 0, 0, 1, 1), rect('B', 5, 0, 1, 1)] }] });
  ui.click(ui.button('가로 간격 같게'));
  assert.strictEqual(panelStatus(ui), '객체를 3개 이상 선택하세요.');
  ui.click(ui.find('radiobutton', '직접 입력'));
  ui.type(ui.after('간격:', 'edittext'), 'abc');
  const sent = env.bridgeBodies.length;
  ui.click(ui.button('가로 간격 같게'));
  assert.strictEqual(panelStatus(ui), '간격은 숫자로 입력해 주세요.');
  assert.strictEqual(env.bridgeBodies.length, sent, 'nothing sent for invalid input');

  ({ env, ui } = openPanel({ documents: [] }));
  ui.click(ui.button('세로 간격 같게'));
  assert.strictEqual(panelStatus(ui), '열린 문서가 없습니다.');

  ({ env, ui } = openPanel({ documents: [{ textEditing: true }] }));
  ui.click(ui.button('가로 간격 같게'));
  assert.match(panelStatus(ui), /^텍스트 편집 중입니다/);
});

test('essential: clipping mask and stroke-inclusive bounds', () => {
  const clip = () => ({
    type: 'GroupItem', name: 'clip', clipped: true, bounds: [0, 100, 200, -100],
    children: [
      { type: 'PathItem', name: 'mask', clipping: true, bounds: [50, 50, 70, 30] },
      { type: 'PathItem', name: 'art', bounds: [0, 100, 200, -100] },
    ],
  });
  let { env, ui } = openPanel({ documents: [{ selection: [rect('X', 0, 50, 20, 20), clip(), rect('Y', 150, 50, 20, 20, { stroke: 2 })] }] });
  ui.click(ui.button('가로 간격 같게'));
  assertBounds(specOf(env, 'clip').bounds, [24.5, 100, 224.5, -100], 'clip moved by the mask position (visible bounds)');
  ({ env, ui } = openPanel({ documents: [{ selection: [rect('X', 0, 50, 20, 20), clip(), rect('Y', 150, 50, 20, 20, { stroke: 2 })] }] }));
  ui.click(ui.find('checkbox', '선 두께 포함'));
  ui.click(ui.button('가로 간격 같게'));
  assertBounds(specOf(env, 'clip').bounds, [25, 100, 225, -100], 'clip with geometric bounds');
});

test('essential: point text keeps its place when justification changes (single and multi-line)', () => {
  const { env, ui } = openPanel({
    documents: [{ selection: [ptext('one', [100, 50], [[60, 'LEFT']]), ptext('multi', [0, 0], [[100, 'LEFT'], [60, 'LEFT'], [80, 'LEFT']])] }],
  });
  ui.selectTab('텍스트');
  const before1 = liveBounds(env, 'one');
  const before2 = liveBounds(env, 'multi');
  ui.click(ui.button('가운데'));
  assertBounds(liveBounds(env, 'one'), before1, 'single line stays');
  assertBounds(liveBounds(env, 'multi'), before2, 'multi-line box stays');
  assert.deepStrictEqual(specOf(env, 'one').text.anchor, [130, 50]);
  assert.strictEqual(specOf(env, 'one').text.paragraphs[0].justification, 'CENTER');
  assert.strictEqual(panelStatus(ui), '가운데 정렬: 포인트 2개(제자리 유지)');
  ui.click(ui.button('오른쪽'));
  assertBounds(liveBounds(env, 'multi'), before2, 'still in place after RIGHT');
  assert.deepStrictEqual(specOf(env, 'multi').text.anchor, [100, 0]);
  ui.click(ui.button('왼쪽'));
  assertBounds(liveBounds(env, 'one'), before1, 'back to LEFT');
  assert.deepStrictEqual(specOf(env, 'one').text.anchor, [100, 50]);
});

test('essential: mixed old justification keeps the new side; vertical and rotated text', () => {
  const { env, ui } = openPanel({
    documents: [{ selection: [
      ptext('mixed', [0, 0], [[100, 'LEFT'], [50, 'RIGHT']]),
      ptext('vert', [0, 0], [[60, 'LEFT']], { orientation: 'v' }),
      ptext('rot', [10, 10], [[80, 'LEFT']], { rotation: 30 }),
    ] }],
  });
  ui.selectTab('텍스트');
  const vert = liveBounds(env, 'vert');
  const rot = liveBounds(env, 'rot');
  ui.click(ui.button('가운데'));
  const mixed = liveBounds(env, 'mixed');
  assert.ok(near(mixed[0], -25) && near(mixed[2], 75), 'mixed: box centre kept at 25, got ' + mixed);
  assertBounds(liveBounds(env, 'vert'), vert, 'vertical text stays');
  assertBounds(liveBounds(env, 'rot'), rot, 'rotated single line stays');
});

test('essential: area and path text are justified in place; justify buttons skip point text', () => {
  const { env, ui } = openPanel({
    documents: [{ selection: [
      boxText('area', 'area', [0, 100, 200, 0], [[150, 'LEFT']]),
      boxText('onpath', 'path', [300, 100, 400, 50], [[80, 'LEFT']]),
      ptext('pt', [500, 0], [[40, 'LEFT']]),
    ] }],
  });
  ui.selectTab('텍스트');
  ui.click(ui.button('가운데'));
  assert.strictEqual(panelStatus(ui), '가운데 정렬: 포인트 1개(제자리 유지), 영역 1개, 패스 1개(위치 유지 안 됨)');
  assert.deepStrictEqual(specOf(env, 'area').text.frame, [0, 100, 200, 0]);
  assert.strictEqual(specOf(env, 'area').text.paragraphs[0].justification, 'CENTER');
  assert.strictEqual(specOf(env, 'onpath').text.paragraphs[0].justification, 'CENTER');
  ui.click(ui.button('양쪽 정렬'));
  assert.strictEqual(specOf(env, 'area').text.paragraphs[0].justification, 'FULLJUSTIFYLASTLINELEFT');
  assert.strictEqual(specOf(env, 'pt').text.paragraphs[0].justification, 'CENTER', 'point text untouched');
  assert.strictEqual(panelStatus(ui), '양쪽 정렬: 영역 1개, 패스 1개(위치 유지 안 됨) / 포인트 텍스트 1개는 양쪽 정렬을 쓸 수 없어 건너뜀');
  ui.click(ui.button('강제 양쪽'));
  assert.strictEqual(specOf(env, 'area').text.paragraphs[0].justification, 'FULLJUSTIFY');
});

test('essential: text inside groups; non-text selection; locked text reported', () => {
  const group = { type: 'GroupItem', name: 'grp', bounds: [0, 20, 300, -40], children: [rect('shape', 200, 20, 10, 10), ptext('inner', [0, 0], [[60, 'LEFT']])] };
  let { env, ui } = openPanel({ documents: [{ selection: [group] }] });
  const inner = env.ai.documents[0]._items[0].pageItems[1];
  const before = Array.from(inner.geometricBounds);
  ui.selectTab('텍스트');
  ui.click(ui.button('오른쪽'));
  assertBounds(Array.from(inner.geometricBounds), before, 'text in group stays');
  assert.strictEqual(panelStatus(ui), '오른쪽 정렬: 포인트 1개(제자리 유지)');

  ({ env, ui } = openPanel({ documents: [{ selection: [rect('a', 0, 0, 1, 1)] }] }));
  ui.selectTab('텍스트');
  ui.click(ui.button('가운데'));
  assert.strictEqual(panelStatus(ui), '텍스트를 선택하세요. (그룹 안의 텍스트도 됩니다)');

  ({ env, ui } = openPanel({ documents: [{ selection: [ptext('ok', [0, 0], [[50, 'LEFT']]), ptext('locked', [0, 50], [[50, 'LEFT']], {}), rect('r', 0, 0, 1, 1)] }] }));
  specOf(env, 'locked').locked = true;
  ui.selectTab('텍스트');
  ui.click(ui.button('가운데'));
  assert.strictEqual(panelStatus(ui), '가운데 정렬: 포인트 1개(제자리 유지) / 1개 실패');
});

test('essential: editing text changes only the selected paragraphs; a bare cursor changes the story', () => {
  let { env, ui } = openPanel({
    documents: [{ selection: [ptext('edit', [0, 0], [[100, 'LEFT'], [60, 'LEFT']])], textEditing: { item: 0, paragraphs: [1], length: 4 } }],
  });
  ui.selectTab('텍스트');
  ui.click(ui.button('가운데'));
  const m = specOf(env, 'edit').text;
  assert.deepStrictEqual(m.paragraphs.map((p) => p.justification), ['LEFT', 'CENTER']);
  const b = liveBounds(env, 'edit');
  assert.ok(near(b[0], -15) && near(b[2], 115), 'box centre kept at 50: ' + b);

  ({ env, ui } = openPanel({
    documents: [{ selection: [ptext('caret', [0, 0], [[100, 'LEFT'], [60, 'LEFT']])], textEditing: { item: 0, length: 0 } }],
  }));
  const before = liveBounds(env, 'caret');
  ui.selectTab('텍스트');
  ui.click(ui.button('오른쪽'));
  assert.deepStrictEqual(specOf(env, 'caret').text.paragraphs.map((p) => p.justification), ['RIGHT', 'RIGHT']);
  assertBounds(liveBounds(env, 'caret'), before, 'caret: whole story, box stays');
});

test('essential: falls back to per-paragraph changes and skips empty paragraphs', () => {
  const { env, ui } = openPanel({
    documents: [{ selection: [ptext('fb', [0, 0], [[80, 'LEFT'], { empty: true }], { rangeSetThrows: true })] }],
  });
  const before = liveBounds(env, 'fb');
  ui.selectTab('텍스트');
  ui.click(ui.button('가운데'));
  assert.deepStrictEqual(specOf(env, 'fb').text.paragraphs.map((p) => p.justification), ['CENTER', 'LEFT']);
  assertBounds(liveBounds(env, 'fb'), before, 'stays');
});

test('essential: settings and window position are remembered; unit switch converts the gap', () => {
  const root = fs.mkdtempSync(path.join(TMP, 'essential-persist-'));
  let { ui, win } = openPanel({ root, documents: [{}] });
  ui.click(ui.find('radiobutton', '직접 입력'));
  ui.type(ui.after('간격:', 'edittext'), '3');
  ui.select(ui.after('간격:', 'dropdownlist'), 1);
  assert.strictEqual(ui.after('간격:', 'edittext').text, '0.3');
  ui.select(ui.after('기준:', 'dropdownlist'), 2);
  win.location = [300, 200];
  win.close();
  ({ ui, win } = openPanel({ root, documents: [{}] }));
  assert.strictEqual(ui.find('radiobutton', '직접 입력')._state.value, true);
  assert.strictEqual(ui.after('간격:', 'edittext').text, '0.3');
  assert.strictEqual(ui.after('간격:', 'dropdownlist').selection.text, 'cm');
  assert.strictEqual(ui.after('기준:', 'dropdownlist').selection.index, 2);
  assert.deepStrictEqual(Array.from(win.location), [300, 200]);
});

test('essential: off-screen saved position falls back to centre', () => {
  const root = fs.mkdtempSync(path.join(TMP, 'essential-offscreen-'));
  fs.mkdirSync(path.join(root, 'userData/IllustratorUIScripts'), { recursive: true });
  fs.writeFileSync(path.join(root, 'userData/IllustratorUIScripts/COC_illust_Essential.ini'), 'windowX=5000\nwindowY=100');
  const ini = fs.readFileSync(path.join(root, 'userData/IllustratorUIScripts/COC_illust_Essential.ini'), 'utf8');
  assert.strictEqual(ini.split('\n').length, 2, 'two settings lines');
  let { win } = openPanel({ root, documents: [{}] });
  assert.deepStrictEqual(Array.from(win.location), [100, 100], 'not moved off-screen');
  fs.writeFileSync(path.join(root, 'userData/IllustratorUIScripts/COC_illust_Essential.ini'), 'windowX=640\nwindowY=480');
  ({ win } = openPanel({ root, documents: [{}] }));
  assert.deepStrictEqual(Array.from(win.location), [640, 480], 'on-screen position restored');
});

// ---- COC_illust Essential: new features ------------------------------------
const rotRect = (name, cx, cy, w, h, angle, extra) => Object.assign({ type: 'PathItem', name, geo: { cx, cy, w, h }, angle, bounds: [0, 0, 0, 0] }, extra || {});
const placed = (name, cx, cy, w, h, angle, extra) => Object.assign(rotRect(name, cx, cy, w, h, angle, extra), { type: 'PlacedItem' });
const raster = (name, cx, cy, w, h, angle, extra) => Object.assign(rotRect(name, cx, cy, w, h, angle, extra), { type: 'RasterItem' });
const noLeaks = (env) => assert.deepStrictEqual(env.tempLeaks(), [], 'temporary copies left in the document');
const tagAngle = (spec) => {
  const tag = spec.tags.find((t) => t.name === 'BBAccumRotation');
  return tag ? parseFloat(tag.value) * 180 / Math.PI : null;
};
const center = (b) => [(b[0] + b[2]) / 2, (b[1] + b[3]) / 2];
const turn = (p, c, deg) => {
  const th = deg * Math.PI / 180;
  return [c[0] + (p[0] - c[0]) * Math.cos(th) - (p[1] - c[1]) * Math.sin(th), c[1] + (p[0] - c[0]) * Math.sin(th) + (p[1] - c[1]) * Math.cos(th)];
};

test('essential: eyedropper reads the gap between two objects and applies it elsewhere, exactly', () => {
  const { env, ui } = openPanel({
    documents: [{
      selection: [rect('L1', 0, 0, 10, 10), rect('L2', 25, 3, 10, 10)],
      unselected: [rect('X', 0, -50, 10, 10), rect('Y', 30, -50, 20, 10), rect('Z', 100, -50, 5, 10)],
    }],
  });
  ui.click(ui.button('스포이드'));
  assert.strictEqual(ui.after('간격:', 'edittext').text, '5.292');
  assert.strictEqual(ui.find('radiobutton', '직접 입력')._state.value, true);
  assert.strictEqual(panelStatus(ui), '가로 간격을 가져왔습니다: 5.292 mm\n다른 객체를 선택하고 [가로 간격 같게]를 누르세요.');
  env.ai.documents[0]._select(['X', 'Y', 'Z']);
  ui.click(ui.button('가로 간격 같게'));
  assertBounds(specOf(env, 'X').bounds, [0, -50, 10, -60], 'X stays');
  assertBounds(specOf(env, 'Y').bounds, [25, -50, 45, -60], 'Y exactly 15 pt after X');
  assertBounds(specOf(env, 'Z').bounds, [60, -50, 65, -60], 'Z exactly 15 pt after Y');
  // typing a new value replaces the picked one
  ui.type(ui.after('간격:', 'edittext'), '10');
  ui.click(ui.button('가로 간격 같게'));
  assert.ok(near(specOf(env, 'Y').bounds[0], 10 + 10 * MM));
  noLeaks(env);
});

test('essential: eyedropper picks the vertical gap, reports overlap, needs exactly two objects', () => {
  let { env, ui } = openPanel({ documents: [{ selection: [rect('A', 0, 0, 10, 10), rect('B', 2, -18, 10, 10)] }] });
  ui.select(ui.after('간격:', 'dropdownlist'), 2);
  ui.click(ui.button('스포이드'));
  assert.strictEqual(ui.after('간격:', 'edittext').text, '8');
  assert.match(panelStatus(ui), /^세로 간격을 가져왔습니다: 8 pt\n/);
  ({ env, ui } = openPanel({ documents: [{ selection: [rect('A', 0, 0, 10, 10), rect('B', 5, -5, 10, 10)] }] }));
  ui.select(ui.after('간격:', 'dropdownlist'), 2);
  ui.click(ui.button('스포이드'));
  assert.match(panelStatus(ui), /^가로 간격을 가져왔습니다: -5 pt \(겹쳐 있음\)/);
  ({ env, ui } = openPanel({ documents: [{ selection: [rect('A', 0, 0, 1, 1), rect('B', 5, 0, 1, 1), rect('C', 9, 0, 1, 1)] }] }));
  ui.click(ui.button('스포이드'));
  assert.strictEqual(panelStatus(ui), '간격을 잴 두 객체를 선택하세요.');
});

test('essential: tidy up finds rows and columns and uses the average gaps', () => {
  // two rough rows; E is bigger. Row gaps 12, 9 / 9, 5 → 8.75 pt; row distance 18 pt
  const { env, ui } = openPanel({
    documents: [{ selection: [
      rect('E', 20, -29, 20, 12), rect('A', 0, 0, 10, 10), rect('F', 45, -31, 10, 10),
      rect('C', 41, -1, 10, 10), rect('D', 1, -30, 10, 10), rect('B', 22, 1, 10, 10),
    ] }],
  });
  ui.click(ui.button('격자로 정리'));
  assertBounds(specOf(env, 'A').bounds, [0, 1, 10, -9], 'A');
  assertBounds(specOf(env, 'B').bounds, [23.75, 1, 33.75, -9], 'B centred in the wide column');
  assertBounds(specOf(env, 'C').bounds, [47.5, 1, 57.5, -9], 'C');
  assertBounds(specOf(env, 'D').bounds, [0, -28, 10, -38], 'D centred in the tall row');
  assertBounds(specOf(env, 'E').bounds, [18.75, -27, 38.75, -39], 'E');
  assertBounds(specOf(env, 'F').bounds, [47.5, -28, 57.5, -38], 'F');
  assert.strictEqual(panelStatus(ui), '격자로 정리했습니다: 6개, 2행 × 3열\n간격 가로 3.087 mm · 세로 6.35 mm');
});

test('essential: tidy up with a typed gap centres a single row', () => {
  const g = 5 * MM;
  const { env, ui } = openPanel({ documents: [{ selection: [rect('A', 0, 0, 10, 10), rect('B', 20, 5, 10, 20), rect('C', 45, -2, 10, 6)] }] });
  ui.click(ui.find('radiobutton', '직접 입력'));
  ui.type(ui.after('간격:', 'edittext'), '5');
  ui.click(ui.button('격자로 정리'));
  assertBounds(specOf(env, 'A').bounds, [0, 0, 10, -10], 'A');
  assertBounds(specOf(env, 'B').bounds, [10 + g, 5, 20 + g, -15], 'B');
  assertBounds(specOf(env, 'C').bounds, [20 + 2 * g, -2, 30 + 2 * g, -8], 'C');
  assert.match(panelStatus(ui), /1행 × 3열\n간격 가로 5 mm · 세로 5 mm$/);
});

test('essential: match size (width to largest, height to smallest with ratio, both sides to the top object)', () => {
  const items = () => [rect('A', 0, 0, 10, 20), rect('B', 50, 0, 30, 15), rect('C', 100, 0, 20, 40)];
  let { env, ui } = openPanel({ documents: [{ selection: items() }] });
  ui.selectTab('간격 · 크기');
  ui.click(ui.find('checkbox', '비율 유지')); // on by default → off
  ui.click(ui.button('크기 맞추기'));
  assertBounds(specOf(env, 'A').bounds, [-10, 0, 20, -20], 'A width 30 around its centre');
  assertBounds(specOf(env, 'B').bounds, [50, 0, 80, -15], 'B is the reference');
  assertBounds(specOf(env, 'C').bounds, [95, 0, 125, -40], 'C width 30');
  assert.strictEqual(panelStatus(ui), '크기를 맞췄습니다: 2개 → 폭 10.583 mm');

  ({ env, ui } = openPanel({ documents: [{ selection: items() }] }));
  ui.selectTab('간격 · 크기');
  ui.select(ui.after('맞출 크기:', 'dropdownlist'), 1);
  ui.select(ui.after('기준 객체:', 'dropdownlist'), 1);
  ui.click(ui.button('크기 맞추기'));
  assertBounds(specOf(env, 'A').bounds, [1.25, -2.5, 8.75, -17.5], 'A height 15, ratio kept');
  assertBounds(specOf(env, 'C').bounds, [106.25, -12.5, 113.75, -27.5], 'C height 15, ratio kept');
  assert.strictEqual(panelStatus(ui), '크기를 맞췄습니다: 2개 → 높이 5.292 mm');

  ({ env, ui } = openPanel({ documents: [{ selection: items() }] }));
  ui.selectTab('간격 · 크기');
  ui.select(ui.after('맞출 크기:', 'dropdownlist'), 2);
  ui.select(ui.after('기준 객체:', 'dropdownlist'), 2);
  ui.click(ui.button('크기 맞추기'));
  assertBounds(specOf(env, 'B').bounds, [60, -5, 70, -10], 'B fits inside 10 × 20 (ratio kept)');
  assertBounds(specOf(env, 'C').bounds, [105, -10, 115, -30], 'C becomes 10 × 20');
  ui.click(ui.find('checkbox', '비율 유지'));
  ui.click(ui.button('크기 맞추기'));
  assertBounds(specOf(env, 'B').bounds, [60, 2.5, 70, -17.5], 'B exactly 10 × 20 without ratio');
  assert.strictEqual(panelStatus(ui), '크기를 맞췄습니다: 2개 → 폭 3.528 mm · 높이 7.056 mm');
});

test('essential: match size corrects for strokes and skips zero-size objects', () => {
  let { env, ui } = openPanel({ documents: [{ selection: [rect('S', 0, 0, 10, 10, { stroke: 2 }), rect('BIG', 50, 0, 30, 30)] }] });
  ui.selectTab('간격 · 크기');
  ui.click(ui.button('크기 맞추기'));
  const vb = Array.from(env.ai.documents[0]._items[0].visibleBounds);
  assert.ok(Math.abs(vb[2] - vb[0] - 30) < 0.01, 'visible width 30 incl. stroke, got ' + (vb[2] - vb[0]));
  assert.ok(env.resizeCalls.length >= 2 && env.resizeCalls.length <= 4, 'corrected in a few passes');

  ({ env, ui } = openPanel({ documents: [{ selection: [rect('line', 0, 0, 0, 20), rect('A', 10, 0, 10, 10), rect('B', 30, 0, 20, 10)] }] }));
  ui.selectTab('간격 · 크기');
  ui.click(ui.button('크기 맞추기'));
  assert.strictEqual(panelStatus(ui), '크기를 맞췄습니다: 1개 → 폭 7.056 mm\n크기가 0이라 건너뛴 객체 1개');
});

test('essential: reset rotation for paths (tag), text and images (matrix), mirrored images', () => {
  const pathText = () => {
    const t = Object.assign(boxText('PT', 'path', [1000, 10, 1060, 0], [[50, 'LEFT']]), { tagAngle: 30 });
    Object.assign(t.text, { rotation: 30, fixedMatrix: true });
    return t;
  };
  const selection = () => [
    rotRect('P', 0, 0, 20, 10, 30, { tagAngle: 30 }),
    ptext('T', [200, 0], [[60, 'LEFT'], [30, 'LEFT']], { rotation: 20 }),
    placed('I', 400, 0, 40, 20, -15),
    placed('M', 500, 0, 40, 20, 30, { flip: true }),
    rotRect('Q', 600, 0, 10, 10, 0),
    raster('R0', 700, 0, 40, 20, 0),
    raster('R', 800, 0, 40, 20, 25),
    raster('RM', 900, 0, 40, 20, 30, { flip: true }),
    pathText(),
  ];
  for (const matrixSign of [1, -1]) {
    const { env, ui } = openPanel({ matrixSign, documents: [{ selection: selection() }] });
    const t0 = liveBounds(env, 'T');
    const anchor0 = specOf(env, 'T').text.anchor.slice();
    ui.selectTab('회전');
    ui.click(ui.button('0°로 초기화'));
    assert.ok(near(specOf(env, 'P').angle, 0), 'P straight');
    assert.strictEqual(tagAngle(specOf(env, 'P')), null, 'P tag cleared');
    assert.ok(near(specOf(env, 'T').text.rotation, 0), 'T straight (matrix sign ' + matrixSign + ')');
    const expected = turn(anchor0, center(t0), -20);
    assert.ok(near(specOf(env, 'T').text.anchor[0], expected[0]) && near(specOf(env, 'T').text.anchor[1], expected[1]),
      'T turned about its centre without drift');
    assert.ok(near(specOf(env, 'I').angle, 0), 'I straight');
    assert.ok(near(specOf(env, 'M').angle, 0) && specOf(env, 'M').flip === true, 'mirrored image straight, still mirrored');
    assert.ok(near(specOf(env, 'Q').angle, 0), 'Q untouched');
    assert.ok(near(specOf(env, 'R0').angle, 0), 'straight embedded image not turned upside down (its matrix is flipped)');
    assert.ok(near(specOf(env, 'R').angle, 0), 'embedded image straight');
    assert.ok(near(specOf(env, 'RM').angle, 0) && specOf(env, 'RM').flip === true, 'mirrored embedded image straight');
    assert.ok(near(specOf(env, 'PT').text.rotation, 0) && tagAngle(specOf(env, 'PT')) === null,
      'text whose matrix does not follow rotation falls back to the tag');
    noLeaks(env);
    assert.strictEqual(panelStatus(ui), '회전을 0°로 초기화했습니다: 8개\n회전 정보가 없는 1개는 그대로 두었습니다.');
  }
});

test('essential: match the top object angle, set a typed angle, report locked objects', () => {
  let { env, ui } = openPanel({
    documents: [{ selection: [rotRect('TOP', 0, 0, 20, 10, 45, { tagAngle: 45 }), rotRect('Q', 50, 0, 20, 10, 10, { tagAngle: 10 }), ptext('T', [100, 0], [[40, 'LEFT']])] }],
  });
  ui.selectTab('회전');
  ui.click(ui.button('맨 위 객체 각도로'));
  assert.ok(near(specOf(env, 'Q').angle, 45) && near(tagAngle(specOf(env, 'Q')), 45), 'Q at 45°, tag updated');
  assert.ok(near(specOf(env, 'T').text.rotation, 45) && near(tagAngle(specOf(env, 'T')), 45), 'T at 45°');
  assert.ok(near(specOf(env, 'TOP').angle, 45), 'reference untouched');
  assert.strictEqual(panelStatus(ui), '맨 위 객체 각도(45°)로 맞췄습니다: 2개');

  ui.type(ui.after('각도:', 'edittext'), 'abc');
  ui.click(ui.button('각도 적용'));
  assert.strictEqual(panelStatus(ui), '각도는 숫자로 입력해 주세요.');
  ui.type(ui.after('각도:', 'edittext'), '-15');
  ui.click(ui.button('각도 적용'));
  for (const n of ['TOP', 'Q']) assert.ok(near(specOf(env, n).angle, -15) && near(tagAngle(specOf(env, n)), -15), n + ' at -15°');
  assert.ok(near(specOf(env, 'T').text.rotation, -15), 'T at -15°');
  assert.strictEqual(panelStatus(ui), '-15°로 맞췄습니다: 3개');

  ({ env, ui } = openPanel({ documents: [{ selection: [rotRect('A', 0, 0, 10, 10, 20, { tagAngle: 20 }), rotRect('L', 50, 0, 10, 10, 20, { tagAngle: 20, locked: true })] }] }));
  ui.selectTab('회전');
  ui.click(ui.button('0°로 초기화'));
  assert.strictEqual(panelStatus(ui), '회전을 0°로 초기화했습니다: 1개\n1개 실패 (잠긴 객체?)');
  ({ env, ui } = openPanel({ documents: [{ selection: [rotRect('A', 0, 0, 10, 10, 20)] }] }));
  ui.selectTab('회전');
  ui.click(ui.button('맨 위 객체 각도로'));
  assert.strictEqual(panelStatus(ui), '객체를 2개 이상 선택하세요.');
});

test('essential: baseline alignment of point text (left, top, bottom, average) and other objects', () => {
  const texts = () => [ptext('T2', [50, 97], [[20, 'LEFT']]), ptext('T1', [0, 100], [[20, 'LEFT']]), ptext('T3', [100, 103], [[20, 'LEFT']])];
  const cases = [[0, 100], [1, 103], [2, 97], [3, 100]];
  for (const [index, y] of cases) {
    const { env, ui } = openPanel({ documents: [{ selection: texts() }] });
    ui.selectTab('텍스트');
    ui.select(ui.after('기준선 위치:', 'dropdownlist'), index);
    ui.click(ui.button('기준선 맞추기'));
    for (const n of ['T1', 'T2', 'T3']) assert.ok(near(specOf(env, n).text.anchor[1], y), `${n} baseline ${y} (option ${index})`);
    assert.strictEqual(panelStatus(ui), '기준선을 맞췄습니다: 텍스트 3개');
  }
  let { env, ui } = openPanel({
    documents: [{ selection: texts().concat([rect('icon', 150, 120, 20, 15), boxText('area', 'area', [0, 50, 100, 0], [[80, 'LEFT']])]) }],
  });
  ui.selectTab('텍스트');
  ui.click(ui.find('checkbox', '텍스트가 아닌 객체는 아랫변을 맞춤'));
  ui.click(ui.button('기준선 맞추기'));
  assertBounds(specOf(env, 'icon').bounds, [150, 115, 170, 100], 'icon bottom on the baseline');
  assertBounds(specOf(env, 'area').text.frame, [0, 50, 100, 0], 'area text not moved');
  assert.strictEqual(panelStatus(ui), '기준선을 맞췄습니다: 텍스트 3개, 객체 1개\n영역 · 패스 · 세로 텍스트 1개는 제외했습니다.');
  ({ env, ui } = openPanel({ documents: [{ selection: [boxText('area', 'area', [0, 50, 100, 0], [[80, 'LEFT']]), rect('r', 0, 0, 1, 1)] }] }));
  ui.selectTab('텍스트');
  ui.click(ui.button('기준선 맞추기'));
  assert.strictEqual(panelStatus(ui), '가로쓰기 포인트 텍스트를 선택하세요.');
});

test('essential: word spacing tracks only the spaces (set, +/-, reset, emoji, editing range)', () => {
  let { env, ui } = openPanel({
    documents: [{ selection: [ptext('W', [0, 0], [[100, 'LEFT']], { contents: 'Hello World Foo　Bar' })] }],
  });
  ui.selectTab('텍스트');
  ui.type(ui.after('값:', 'edittext'), '-50');
  const before = env.counts.charAccess;
  ui.click(ui.button('적용'));
  const m = specOf(env, 'W').text;
  const spaces = [5, 11, 15];
  m.tracking.forEach((v, i) => assert.strictEqual(v, spaces.includes(i) ? -50 : 0, 'char ' + i));
  assert.strictEqual(env.counts.charAccess - before, 3, 'only the spaces were touched');
  assert.strictEqual(panelStatus(ui), '어간 -50 적용: 띄어쓰기 3개');
  ui.click(ui.button('+10'));
  assert.strictEqual(m.tracking[5], -40);
  assert.strictEqual(ui.after('값:', 'edittext').text, '-40');
  ui.click(ui.button('-10'));
  ui.click(ui.button('-10'));
  assert.strictEqual(m.tracking[11], -60);
  ui.click(ui.button('0으로'));
  assert.ok(m.tracking.every((v) => v === 0));
  assert.strictEqual(ui.after('값:', 'edittext').text, '0');

  ({ env, ui } = openPanel({ documents: [{ selection: [ptext('E', [0, 0], [[100, 'LEFT']], { contents: 'A😀 B C' })] }] }));
  ui.selectTab('텍스트');
  ui.type(ui.after('값:', 'edittext'), '100');
  ui.click(ui.button('적용'));
  assert.deepStrictEqual(specOf(env, 'E').text.tracking, [0, 0, 100, 0, 100, 0], 'emoji counted as one character');

  ({ env, ui } = openPanel({
    documents: [{ selection: [ptext('R', [0, 0], [[100, 'LEFT']], { contents: 'one two three' })], textEditing: { item: 0, start: 0, length: 5 } }],
  }));
  ui.selectTab('텍스트');
  ui.type(ui.after('값:', 'edittext'), '30');
  ui.click(ui.button('적용'));
  assert.deepStrictEqual(specOf(env, 'R').text.tracking.map((v, i) => (v ? i : -1)).filter((i) => i >= 0), [3], 'only the space inside the edited range');

  ({ env, ui } = openPanel({ documents: [{ selection: [ptext('N', [0, 0], [[100, 'LEFT']], { contents: 'NoSpaces' })] }] }));
  ui.selectTab('텍스트');
  ui.click(ui.button('적용'));
  assert.strictEqual(panelStatus(ui), '선택한 텍스트에 띄어쓰기가 없습니다.');
  ui.type(ui.after('값:', 'edittext'), 'x');
  ui.click(ui.button('적용'));
  assert.strictEqual(panelStatus(ui), '어간 값은 숫자로 입력해 주세요. (예: -50, 100)');
});

test('essential: glyph-shape measuring for spacing and the eyedropper (text and text in groups)', () => {
  const texts = () => [
    ptext('T1', [0, 0], [[30, 'LEFT']]),
    ptext('T2', [50, 0], [[60, 'LEFT']], { glyphInset: [10, 2, 0, 3] }),
    ptext('T3', [150, 0], [[20, 'LEFT']]),
  ];
  let { env, ui } = openPanel({ documents: [{ selection: texts() }] });
  ui.click(ui.button('가로 간격 같게'));
  assert.ok(near(specOf(env, 'T2').text.anchor[0], 60), 'text boxes: T2 moves 10');
  ({ env, ui } = openPanel({ documents: [{ selection: texts() }] }));
  ui.click(ui.find('checkbox', '글자 모양 기준'));
  ui.click(ui.button('가로 간격 같게'));
  assert.ok(near(specOf(env, 'T2').text.anchor[0], 55), 'letter shapes: T2 moves 5');
  noLeaks(env);

  const group = () => ({
    type: 'GroupItem', name: 'G', bounds: [0, 0, 30, -15],
    children: [rect('gr', 0, 0, 10, 10), ptext('gt', [0, -12], [[30, 'LEFT']], { glyphInset: [0.5, 2, 5, 3] })],
  });
  ({ env, ui } = openPanel({ documents: [{ selection: [group(), rect('R', 40, 0, 10, 10)] }] }));
  ui.select(ui.after('간격:', 'dropdownlist'), 2);
  ui.click(ui.button('스포이드'));
  assert.strictEqual(ui.after('간격:', 'edittext').text, '10', 'group box');
  ui.click(ui.find('checkbox', '글자 모양 기준'));
  ui.click(ui.button('스포이드'));
  assert.strictEqual(ui.after('간격:', 'edittext').text, '15', 'group with outlined text');
  noLeaks(env);
});

test('essential: tabs, remembered tab and options', () => {
  const root = fs.mkdtempSync(path.join(TMP, 'essential-tabs-'));
  let { ui, win } = openPanel({ root, documents: [{}] });
  assert.throws(() => ui.click(ui.button('기준선 맞추기')), /not selected/);
  ui.selectTab('텍스트');
  ui.click(ui.find('checkbox', '글자 모양 기준'));
  ui.selectTab('간격 · 크기');
  ui.select(ui.after('맞출 크기:', 'dropdownlist'), 2);
  ui.selectTab('정리');
  win.close();
  ({ ui, win } = openPanel({ root, documents: [{}] }));
  assert.strictEqual(ui.find('tab', '정리')._state.parent.selection._state.text, '정리');
  assert.strictEqual(ui.find('checkbox', '글자 모양 기준')._state.value, true);
  assert.strictEqual(ui.after('맞출 크기:', 'dropdownlist').selection.index, 2);

  // Opening must not save: the window has no position yet, so the saved one would be lost.
  const ini = path.join(root, 'userData/IllustratorUIScripts/COC_illust_Essential.ini');
  fs.writeFileSync(ini, 'tab=2\nwindowX=640\nwindowY=480');
  ({ ui, win } = openPanel({ root, documents: [{}] }));
  assert.strictEqual(fs.readFileSync(ini, 'utf8'), 'tab=2\nwindowX=640\nwindowY=480', 'settings untouched by opening');
  assert.strictEqual(ui.find('tab', '텍스트')._state.parent.selection._state.text, '텍스트');
  assert.deepStrictEqual(Array.from(win.location), [640, 480]);
});

// ---- COC_illust Essential: key object, point rotation, organize tab ---------
const pts = (name, points, extra) => Object.assign({ type: 'PathItem', name, points }, extra || {});
const grp = (name, children, extra) => Object.assign({ type: 'GroupItem', name, children, derived: true, bounds: [0, 0, 0, 0] }, extra || {});
const anchorAt = (env, name, i) => env.ai.documents[0]._find(name).points[i];
const pointsBoundsOf = (points) => [Math.min(...points.map((p) => p[0])), Math.max(...points.map((p) => p[1])),
  Math.max(...points.map((p) => p[0])), Math.min(...points.map((p) => p[1]))];
const ALIGN_COMMANDS = ['Vertical Align Top', 'Horizontal Align Right', 'Vertical Align Bottom', 'Horizontal Align Left'];

test('essential: match size to the key object (found with the Align commands, positions restored)', () => {
  const items = () => [rect('A', 0, 0, 10, 10), rect('B', 50, 0, 30, 20), rect('C', 100, 0, 20, 40)];
  let { env, ui } = openPanel({ documents: [{ selection: items(), keyObject: 'B' }] });
  ui.select(ui.after('기준 객체:', 'dropdownlist'), 3);
  ui.click(ui.button('크기 맞추기'));
  assert.deepStrictEqual(env.menuCommands, ALIGN_COMMANDS);
  assertBounds(specOf(env, 'B').bounds, [50, 0, 80, -20], 'key object untouched');
  assertBounds(specOf(env, 'A').bounds, [-10, 10, 20, -20], 'A width 30 around its own centre (ratio kept)');
  assertBounds(specOf(env, 'C').bounds, [95, 10, 125, -50], 'C width 30 around its own centre (ratio kept)');
  assert.strictEqual(panelStatus(ui), '크기를 맞췄습니다: 2개 → 폭 10.583 mm');

  // no key object: everything goes back where it was, nothing is resized
  ({ env, ui } = openPanel({ documents: [{ selection: items() }] }));
  ui.select(ui.after('기준 객체:', 'dropdownlist'), 3);
  ui.click(ui.button('크기 맞추기'));
  assertBounds(specOf(env, 'A').bounds, [0, 0, 10, -10], 'A back in place');
  assertBounds(specOf(env, 'B').bounds, [50, 0, 80, -20], 'B back in place');
  assertBounds(specOf(env, 'C').bounds, [100, 0, 120, -40], 'C back in place');
  assert.strictEqual(env.resizeCalls.length, 0);
  assert.strictEqual(panelStatus(ui), '키 오브젝트를 찾지 못했습니다. 여러 객체를 선택한 뒤 기준 객체를 한 번 더 클릭해 굵은 테두리로 만드세요.');

  // commands that do nothing must not make the first object the key
  ({ env, ui } = openPanel({ documents: [{ selection: items(), keyObject: 'B', menuIgnored: true }] }));
  ui.select(ui.after('기준 객체:', 'dropdownlist'), 3);
  ui.click(ui.button('크기 맞추기'));
  assert.strictEqual(env.resizeCalls.length, 0);
  assert.ok(/^키 오브젝트를 찾지 못했습니다/.test(panelStatus(ui)));

  // other references never touch the Align commands
  ({ env, ui } = openPanel({ documents: [{ selection: items(), keyObject: 'B' }] }));
  ui.click(ui.button('크기 맞추기'));
  assert.deepStrictEqual(env.menuCommands, []);
});

test('essential: point-based rotation levels two anchor points about their middle', () => {
  // bottom edge (0,0) → (100,10) is tilted by atan(0.1) ≈ 5.71°
  const shape = () => pts('P', [[0, 0], [100, 10], [100, 60], [0, 50]], { selectedPoints: [0, 1] });
  let { env, ui } = openPanel({ documents: [{ layers: [{ name: 'L', items: [shape()] }], select: ['P'] }] });
  ui.selectTab('회전');
  ui.click(ui.button('포인트 기준 수평 회전'));
  let a = anchorAt(env, 'P', 0);
  let b = anchorAt(env, 'P', 1);
  assert.ok(near(a[1], b[1], 1e-9), 'points level');
  assert.ok(near((a[0] + b[0]) / 2, 50, 1e-9) && near((a[1] + b[1]) / 2, 5, 1e-9), 'middle of the two points stays');
  assert.ok(near(b[0] - a[0], Math.hypot(100, 10), 1e-9), 'turned, not squashed');
  assert.strictEqual(panelStatus(ui), '두 점이 수평이 되도록 -5.711° 돌렸습니다: 객체 1개');

  // the vertical button on the same (now level) edge turns by 90° the short way
  ui.click(ui.button('포인트 기준 수직 회전'));
  a = anchorAt(env, 'P', 0);
  b = anchorAt(env, 'P', 1);
  assert.ok(near(a[0], b[0], 1e-9), 'points on one vertical line');
  assert.strictEqual(panelStatus(ui), '두 점이 수직이 되도록 -90° 돌렸습니다: 객체 1개');
  ui.click(ui.button('포인트 기준 수직 회전'));
  assert.strictEqual(panelStatus(ui), '두 점이 이미 수직입니다.');
});

test('essential: point rotation turns whole groups, several objects as one, and follows the Transform angle', () => {
  // points on a path inside a compound path inside a group: the whole group turns, other paths too
  const doc = () => ({
    layers: [{
      name: 'L',
      items: [grp('G', [
        { type: 'CompoundPathItem', name: 'CP', paths: [pts('inner', [[0, 0], [50, 5], [50, 30]], { selectedPoints: [0, 1] })], derived: true, bounds: [0, 0, 0, 0] },
        pts('other', [[0, 100], [10, 100], [10, 110]]),
      ], { tags: [{ name: 'BBAccumRotation', value: String(30 * Math.PI / 180) }] })],
    }],
    select: ['CP'],
  });
  let { env, ui } = openPanel({ documents: [doc()] });
  ui.selectTab('회전');
  ui.click(ui.button('포인트 기준 수평 회전'));
  const delta = -Math.atan2(5, 50) * 180 / Math.PI;
  const turned = turn([0, 100], [25, 2.5], delta);
  assert.ok(near(anchorAt(env, 'other', 0)[0], turned[0], 1e-9) && near(anchorAt(env, 'other', 0)[1], turned[1], 1e-9), 'the rest of the group turned with it');
  assert.ok(near(anchorAt(env, 'inner', 0)[1], anchorAt(env, 'inner', 1)[1], 1e-9));
  assert.ok(near(tagAngle(env.ai.documents[0]._find('G')), 30 + delta, 1e-9), 'Transform panel angle follows');
  assert.strictEqual(panelStatus(ui), '두 점이 수평이 되도록 ' + (Math.round(delta * 1000) / 1000) + '° 돌렸습니다: 객체 1개');

  // one point on each of two objects: both turn together (the second point is picked first here)
  ({ env, ui } = openPanel({
    documents: [{
      layers: [{ name: 'L', items: [pts('R', [[100, 10], [120, 10], [120, 30]], { selectedPoints: [0] }), pts('Q', [[0, 0], [-20, 0], [-20, 20]], { selectedPoints: [0] })] }],
      select: ['R', 'Q'],
    }],
  }));
  ui.selectTab('회전');
  ui.click(ui.button('포인트 기준 수평 회전'));
  const r0 = anchorAt(env, 'R', 0);
  const q0 = anchorAt(env, 'Q', 0);
  assert.ok(near(r0[1], q0[1], 1e-9), 'the two points level');
  assert.ok(near(Math.hypot(r0[0] - q0[0], r0[1] - q0[1]), Math.hypot(100, 10), 1e-9), 'kept their distance');
  assert.ok(near((r0[0] + q0[0]) / 2, 50, 1e-9) && near((r0[1] + q0[1]) / 2, 5, 1e-9), 'about their middle');
  assert.ok(r0[0] > q0[0], 'turned the short way (not flipped over)');
  assert.strictEqual(env.ai.documents[0]._find('R').tags.length, 0, 'no Transform angle invented');
  assert.strictEqual(panelStatus(ui), '두 점이 수평이 되도록 -5.711° 돌렸습니다: 객체 2개');
  noLeaks(env);
});

test('essential: point rotation needs exactly two separate points', () => {
  const run1 = (points, selected) => {
    const { env, ui } = openPanel({ documents: [{ layers: [{ name: 'L', items: [pts('P', points, { selectedPoints: selected })] }], select: ['P'] }] });
    ui.selectTab('회전');
    ui.click(ui.button('포인트 기준 수직 회전'));
    assert.strictEqual(env.rotateCalls.length, 0);
    return panelStatus(ui);
  };
  assert.strictEqual(run1([[0, 0], [10, 0], [10, 10]], [2]), '점을 정확히 두 개 선택하세요. (지금 1개) 직접 선택 도구(A)를 쓰세요.');
  assert.strictEqual(run1([[0, 0], [10, 0], [10, 10]], 'all'), '점을 정확히 두 개 선택하세요. (지금 3개 이상) 직접 선택 도구(A)를 쓰세요.');
  assert.strictEqual(run1([[5, 5], [5, 5], [10, 10]], [0, 1]), '두 점이 같은 위치에 있습니다. 떨어진 두 점을 고르세요.');
  const { ui } = openPanel({ documents: [{ selection: [rect('A', 0, 0, 10, 10)] }] });
  ui.selectTab('회전');
  ui.click(ui.button('포인트 기준 수평 회전'));
  assert.strictEqual(panelStatus(ui), '점을 정확히 두 개 선택하세요. (지금 0개) 직접 선택 도구(A)를 쓰세요.');
});

// Artboards placed out of index order: visually A B C in the top row, D below.
const messyBoards = () => [
  { name: 'C', rect: [300, 0, 400, -100] },
  { name: 'A', rect: [0, 5, 100, -95] },
  { name: 'D', rect: [10, -200, 110, -280] },
  { name: 'B', rect: [150, -2, 290, -102] },
];
const messyLayers = () => [
  {
    name: 'Front',
    items: [
      rect('a1', 10, -5, 40, 40), rect('b1', 160, -10, 40, 40), rect('c1', 320, -10, 40, 40, { locked: true }),
      rect('span', 90, -20, 80, 10), rect('off', 600, 0, 20, 20), rect('h1', 60, -210, 20, 20, { hidden: true }),
      grp('g', [rect('g1', 310, -60, 20, 20, { locked: true }), rect('g2', 340, -60, 20, 20)]),
    ],
    layers: [{ name: 'Sub', visible: false, items: [rect('h2', 70, -230, 10, 10)] }],
  },
  { name: 'Back', locked: true, items: [rect('d1', 20, -210, 40, 40)] },
];
const boardRects = (env) => env.ai.documents[0]._artboards.map((a) => [a.name].concat(Array.from(a.artboardRect)));
const openOrganize = (config) => {
  const opened = openPanel(config);
  opened.ui.selectTab('간격 · 크기');
  opened.ui.select(opened.ui.after('간격:', 'dropdownlist'), 2); // pt
  opened.ui.selectTab('정리');
  opened.ui.type(opened.ui.after('간격:', 'edittext'), '20');
  return opened;
};

test('essential: artboard rearrange keeps the placed order, renumbers, moves artwork, restores locks', () => {
  const { env, ui } = openOrganize({ documents: [{ artboards: messyBoards(), activeArtboard: 0, layers: messyLayers() }] });
  assert.strictEqual(ui.find('statictext', 'pt')._state.text, 'pt', 'unit label follows the panel unit');
  ui.click(ui.button('아트보드 리어레인지'));
  assert.deepStrictEqual(boardRects(env), [
    ['A', 0, 5, 100, -95], ['B', 120, 5, 260, -95], ['C', 280, 5, 380, -95], ['D', 0, -115, 100, -195],
  ]);
  const doc = env.ai.documents[0];
  assert.strictEqual(doc._activeArtboard, 2, 'the active artboard (C) is still active');
  assertBounds(doc._find('a1').bounds, [10, -5, 50, -45], 'A did not move');
  assertBounds(doc._find('b1').bounds, [130, -3, 170, -43], 'moved with B');
  assertBounds(doc._find('span').bounds, [60, -13, 140, -23], 'goes with the artboard it overlaps most (B)');
  assertBounds(doc._find('c1').bounds, [300, -5, 340, -45], 'locked object moved with C');
  assertBounds(doc._find('g1').bounds, [290, -55, 310, -75], 'locked object inside a group moved');
  assertBounds(doc._find('d1').bounds, [10, -125, 50, -165], 'object in a locked layer moved with D');
  assertBounds(doc._find('h1').bounds, [50, -125, 70, -145], 'hidden object moved with D');
  assertBounds(doc._find('h2').bounds, [60, -145, 70, -155], 'object in a hidden sublayer moved with D');
  assertBounds(doc._find('off').bounds, [600, 0, 620, -20], 'pasteboard object stays');
  assert.ok(doc._find('c1').locked && doc._find('g1').locked && doc._find('h1').hidden, 'objects locked / hidden again');
  assert.ok(doc._layers[1].locked && doc._layers[0].layers[0].visible === false, 'layers locked / hidden again');
  assert.ok(!doc._find('a1').locked && !doc._find('b1').hidden && !doc._layers[0].locked);
  assert.deepStrictEqual(env.coordinateLog, ['document', 'artboard'], 'document coordinates only while working');
  assert.strictEqual(panelStatus(ui), '아트보드 4개를 2행 × 3열로 정리하고, 놓인 순서대로 번호를 다시 매겼습니다.\n잠긴 것 3개는 잠깐 풀었다가 다시 잠갔습니다.');
});

test('essential: artboard rearrange by column count; canvas overflow puts everything back', () => {
  let { env, ui } = openOrganize({ documents: [{ artboards: messyBoards(), layers: messyLayers() }] });
  ui.click(ui.find('radiobutton', '열 수:'));
  ui.type(ui.after('열 수:', 'edittext'), '2');
  ui.click(ui.button('아트보드 리어레인지'));
  assert.deepStrictEqual(boardRects(env), [
    ['A', 0, 5, 100, -95], ['B', 120, 5, 260, -95], ['C', 0, -115, 100, -215], ['D', 120, -115, 220, -195],
  ]);
  assert.ok(/^아트보드 4개를 2행 × 2열로 정리하고/.test(panelStatus(ui)));

  ({ env, ui } = openOrganize({ canvas: 420, documents: [{ artboards: messyBoards(), layers: messyLayers() }] }));
  ui.type(ui.after('간격:', 'edittext'), '200');
  ui.click(ui.button('아트보드 리어레인지'));
  assert.deepStrictEqual(boardRects(env), messyBoards().map((b) => [b.name].concat(b.rect)), 'artboards back as they were');
  assertBounds(env.ai.documents[0]._find('b1').bounds, [160, -10, 200, -50], 'artwork untouched');
  assert.ok(env.ai.documents[0]._find('c1').locked);
  assert.deepStrictEqual(env.coordinateLog, ['document', 'artboard']);
  assert.strictEqual(panelStatus(ui), '아트보드가 캔버스 밖으로 나가서 정리하지 못했습니다. 간격을 줄이거나 열 수를 바꿔 보세요.');
});

test('essential: artboard rearrange input checks and remembered options', () => {
  const root = fs.mkdtempSync(path.join(TMP, 'essential-organize-'));
  let { env, ui, win } = openPanel({ root, documents: [{ artboards: messyBoards() }] });
  ui.selectTab('정리');
  assert.throws(() => ui.type(ui.after('열 수:', 'edittext'), '3'), /disabled/, 'column count only with 열 수');
  ui.type(ui.after('간격:', 'edittext'), '-5');
  ui.click(ui.button('아트보드 리어레인지'));
  assert.strictEqual(panelStatus(ui), '아트보드 간격은 0 이상의 숫자로 입력해 주세요.');
  ui.type(ui.after('간격:', 'edittext'), '12');
  ui.click(ui.find('radiobutton', '열 수:'));
  for (const bad of ['abc', '0', '2.5']) {
    ui.type(ui.after('열 수:', 'edittext'), bad);
    ui.click(ui.button('아트보드 리어레인지'));
    assert.strictEqual(panelStatus(ui), '열 수는 1 이상의 정수로 입력해 주세요.', bad);
  }
  assert.deepStrictEqual(env.bridgeBodies, [], 'nothing sent');
  ui.type(ui.after('열 수:', 'edittext'), '3');
  ui.click(ui.find('checkbox', '01, 02 …'));
  win.close();
  ({ env, ui, win } = openPanel({ root, documents: [{}] }));
  assert.strictEqual(ui.find('radiobutton', '열 수:')._state.value, true);
  assert.strictEqual(ui.after('열 수:', 'edittext').text, '3');
  assert.strictEqual(ui.find('checkbox', '01, 02 …')._state.value, true);
  ui.selectTab('정리');
  assert.strictEqual(ui.after('간격:', 'edittext').text, '12');
});

test('essential: artboard renaming to plain or padded numbers', () => {
  const boards = (n) => Array.from({ length: n }, (_, i) => ({ name: 'x' + (n - i), rect: [i * 120, 0, i * 120 + 100, -100] }));
  let { env, ui } = openPanel({ documents: [{ artboards: boards(12) }] });
  ui.selectTab('정리');
  ui.click(ui.button('아트보드 리네이밍'));
  assert.deepStrictEqual(env.ai.documents[0]._artboards.map((a) => a.name), ['1', '2', '3', '4', '5', '6', '7', '8', '9', '10', '11', '12']);
  assert.strictEqual(panelStatus(ui), '아트보드 이름을 바꿨습니다: 1 ~ 12 (12개)');
  ui.click(ui.find('checkbox', '01, 02 …'));
  ui.click(ui.button('아트보드 리네이밍'));
  assert.strictEqual(env.ai.documents[0]._artboards.map((a) => a.name).join(','), '01,02,03,04,05,06,07,08,09,10,11,12');
  ({ env, ui } = openPanel({ documents: [{ artboards: boards(3) }] }));
  ui.selectTab('정리');
  ui.click(ui.find('checkbox', '01, 02 …'));
  ui.click(ui.button('아트보드 리네이밍'));
  assert.deepStrictEqual(env.ai.documents[0]._artboards.map((a) => a.name), ['01', '02', '03']);
  assert.strictEqual(panelStatus(ui), '아트보드 이름을 바꿨습니다: 01 ~ 03 (3개)');
});

test('essential: artwork trim clips only what sticks out, in place, with the artboards it touches', () => {
  const doc = () => ({
    artboards: [{ name: '1', rect: [0, 0, 100, -100] }, { name: '2', rect: [100, 0, 200, -100] }, { name: '3', rect: [300, 0, 400, -100] }],
    layers: [
      {
        name: 'Art',
        items: [
          rect('inside', 10, -10, 40, 40),
          rect('bleed', -10, 10, 60, 60),
          rect('span', 80, -10, 40, 40),
          rect('spanOut', 80, 10, 40, 60),
          rect('lockedBleed', 290, -10, 30, 40, { locked: true }),
          rect('off', 500, 0, 50, 50),
          rect('stroke', 0, -60, 90, 30, { stroke: 4 }), // only its stroke sticks out (left)
          rect('guide', -50, -40, 300, 0.001, { guides: true }),
        ],
      },
      { name: 'Hidden', visible: false, items: [rect('hiddenBleed', 350, 10, 20, 20)] },
    ],
  });
  const { env, ui } = openPanel({ documents: [doc()] });
  ui.selectTab('정리');
  ui.click(ui.button('아트워크 트림'));
  const d = env.ai.documents[0];
  const clipOf = (name) => {
    const g = d._find(name)._parentSpec;
    assert.ok(g && g.type === 'GroupItem' && g.clipped, name + ' is in a clipping group');
    const live = g.children.filter((c) => !c._removed);
    assert.strictEqual(live.length, 2, name + ': mask and object');
    assert.strictEqual(live[1].name, name, name + ' sits under the mask');
    return live[0];
  };
  const mask = clipOf('bleed');
  assert.ok(mask.type === 'PathItem' && mask.clipping && !mask.filled && !mask.stroked);
  assertBounds(pointsBoundsOf(mask.points), [0, 0, 100, -100], 'mask = artboard 1');
  const both = clipOf('spanOut');
  assert.strictEqual(both.type, 'CompoundPathItem', 'two artboards: compound mask');
  assert.deepStrictEqual(both.paths.map((p) => pointsBoundsOf(p.points)), [[100, 0, 200, -100], [0, 0, 100, -100]]);
  assert.ok(both.paths.every((p) => p.clipping));
  clipOf('stroke');
  for (const n of ['inside', 'span', 'lockedBleed', 'off', 'guide', 'hiddenBleed']) {
    assert.strictEqual(d._find(n)._parentSpec, null, n + ' untouched');
  }
  assert.deepStrictEqual(d._tree()[0].items, [
    'inside', { GroupItem: ['PathItem', 'bleed'] }, 'span', { GroupItem: ['CompoundPathItem', 'spanOut'] },
    'lockedBleed', 'off', { GroupItem: ['PathItem', 'stroke'] }, 'guide',
  ], 'clipping groups take the place of their objects');
  assert.deepStrictEqual(env.coordinateLog, ['document', 'artboard']);
  assert.strictEqual(panelStatus(ui), '아트보드 밖으로 나간 객체 3개를 아트보드 크기로 잘랐습니다.\n잠기거나 숨긴 객체 2개는 건너뛰었습니다.');

  ui.click(ui.button('아트워크 트림'));
  assert.strictEqual(panelStatus(ui), '아트보드 밖으로 나간 객체가 없습니다.\n잠기거나 숨긴 객체 2개는 건너뛰었습니다.', 'a second run changes nothing');
  noLeaks(env);
});

// ===========================================================================
let failed = 0;
for (const t of tests) {
  try {
    t.fn();
    console.log('  ok  ' + t.name);
  } catch (e) {
    failed++;
    console.log('FAIL  ' + t.name + '\n        ' + String(e && e.message || e).split('\n').join('\n        '));
  }
}
console.log(`\n${tests.length - failed}/${tests.length} passed`);
process.exit(failed ? 1 : 0);
