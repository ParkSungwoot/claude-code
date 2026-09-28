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
  align: path.join(BASE, 'scripts/AlignPlus.jsx'),
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
//  AlignPlus (palette + BridgeTalk)
// ===========================================================================
function openPanel(config) {
  const env = run(S.align, config);
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

test('align+: opens as a palette once; running again reuses it', () => {
  const { env, win } = openPanel({ documents: [{}] });
  assert.strictEqual(env.counts.dialogsShown, 0);
  assert.strictEqual(win._state.type, 'palette');
  env.rerun();
  assert.strictEqual(env.ui.windows.length, 1, 'no second palette');
  win.close();
  env.rerun();
  assert.strictEqual(env.ui.windows.length, 2, 'new palette after closing the old one');
});

test('align+: horizontal equal gaps keep both ends, any selection order', () => {
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
  assert.ok(env.bridgeBodies.length === 1 && /^\(function alignPlusCore\(req\)/.test(env.bridgeBodies[0]));
});

test('align+: vertical equal gaps (top to bottom)', () => {
  const { env, ui } = openPanel({
    documents: [{ selection: [rect('R', 2, -100, 10, 5), rect('P', 0, 0, 10, 10), rect('Q', 5, -30, 10, 30)] }],
  });
  ui.click(ui.button('세로 간격 같게'));
  assertBounds(specOf(env, 'P').bounds, [0, 0, 10, -10], 'P');
  assertBounds(specOf(env, 'Q').bounds, [5, -40, 15, -70], 'Q');
  assertBounds(specOf(env, 'R').bounds, [2, -100, 12, -105], 'R');
  assert.strictEqual(panelStatus(ui), '세로 3개를 간격 10.583 mm로 배열했습니다.');
});

test('align+: fixed gap in mm with start / center / end anchors', () => {
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

test('align+: too few objects, invalid gap, no document, text editing', () => {
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

test('align+: clipping mask and stroke-inclusive bounds', () => {
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
  ui.click(ui.find('checkbox', '선 두께까지 포함한 크기로 계산'));
  ui.click(ui.button('가로 간격 같게'));
  assertBounds(specOf(env, 'clip').bounds, [25, 100, 225, -100], 'clip with geometric bounds');
});

test('align+: point text keeps its place when justification changes (single and multi-line)', () => {
  const { env, ui } = openPanel({
    documents: [{ selection: [ptext('one', [100, 50], [[60, 'LEFT']]), ptext('multi', [0, 0], [[100, 'LEFT'], [60, 'LEFT'], [80, 'LEFT']])] }],
  });
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

test('align+: mixed old justification keeps the new side; vertical and rotated text', () => {
  const { env, ui } = openPanel({
    documents: [{ selection: [
      ptext('mixed', [0, 0], [[100, 'LEFT'], [50, 'RIGHT']]),
      ptext('vert', [0, 0], [[60, 'LEFT']], { orientation: 'v' }),
      ptext('rot', [10, 10], [[80, 'LEFT']], { rotation: 30 }),
    ] }],
  });
  const vert = liveBounds(env, 'vert');
  const rot = liveBounds(env, 'rot');
  ui.click(ui.button('가운데'));
  const mixed = liveBounds(env, 'mixed');
  assert.ok(near(mixed[0], -25) && near(mixed[2], 75), 'mixed: box centre kept at 25, got ' + mixed);
  assertBounds(liveBounds(env, 'vert'), vert, 'vertical text stays');
  assertBounds(liveBounds(env, 'rot'), rot, 'rotated single line stays');
});

test('align+: area and path text are justified in place; justify buttons skip point text', () => {
  const { env, ui } = openPanel({
    documents: [{ selection: [
      boxText('area', 'area', [0, 100, 200, 0], [[150, 'LEFT']]),
      boxText('onpath', 'path', [300, 100, 400, 50], [[80, 'LEFT']]),
      ptext('pt', [500, 0], [[40, 'LEFT']]),
    ] }],
  });
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

test('align+: text inside groups; non-text selection; locked text reported', () => {
  const group = { type: 'GroupItem', name: 'grp', bounds: [0, 20, 300, -40], children: [rect('shape', 200, 20, 10, 10), ptext('inner', [0, 0], [[60, 'LEFT']])] };
  let { env, ui } = openPanel({ documents: [{ selection: [group] }] });
  const inner = env.ai.documents[0]._items[0].pageItems[1];
  const before = Array.from(inner.geometricBounds);
  ui.click(ui.button('오른쪽'));
  assertBounds(Array.from(inner.geometricBounds), before, 'text in group stays');
  assert.strictEqual(panelStatus(ui), '오른쪽 정렬: 포인트 1개(제자리 유지)');

  ({ env, ui } = openPanel({ documents: [{ selection: [rect('a', 0, 0, 1, 1)] }] }));
  ui.click(ui.button('가운데'));
  assert.strictEqual(panelStatus(ui), '텍스트를 선택하세요. (그룹 안의 텍스트도 됩니다)');

  ({ env, ui } = openPanel({ documents: [{ selection: [ptext('ok', [0, 0], [[50, 'LEFT']]), ptext('locked', [0, 50], [[50, 'LEFT']], {}), rect('r', 0, 0, 1, 1)] }] }));
  specOf(env, 'locked').locked = true;
  ui.click(ui.button('가운데'));
  assert.strictEqual(panelStatus(ui), '가운데 정렬: 포인트 1개(제자리 유지) / 1개 실패');
});

test('align+: editing text changes only the selected paragraphs; a bare cursor changes the story', () => {
  let { env, ui } = openPanel({
    documents: [{ selection: [ptext('edit', [0, 0], [[100, 'LEFT'], [60, 'LEFT']])], textEditing: { item: 0, paragraphs: [1], length: 4 } }],
  });
  ui.click(ui.button('가운데'));
  const m = specOf(env, 'edit').text;
  assert.deepStrictEqual(m.paragraphs.map((p) => p.justification), ['LEFT', 'CENTER']);
  const b = liveBounds(env, 'edit');
  assert.ok(near(b[0], -15) && near(b[2], 115), 'box centre kept at 50: ' + b);

  ({ env, ui } = openPanel({
    documents: [{ selection: [ptext('caret', [0, 0], [[100, 'LEFT'], [60, 'LEFT']])], textEditing: { item: 0, length: 0 } }],
  }));
  const before = liveBounds(env, 'caret');
  ui.click(ui.button('오른쪽'));
  assert.deepStrictEqual(specOf(env, 'caret').text.paragraphs.map((p) => p.justification), ['RIGHT', 'RIGHT']);
  assertBounds(liveBounds(env, 'caret'), before, 'caret: whole story, box stays');
});

test('align+: falls back to per-paragraph changes and skips empty paragraphs', () => {
  const { env, ui } = openPanel({
    documents: [{ selection: [ptext('fb', [0, 0], [[80, 'LEFT'], { empty: true }], { rangeSetThrows: true })] }],
  });
  const before = liveBounds(env, 'fb');
  ui.click(ui.button('가운데'));
  assert.deepStrictEqual(specOf(env, 'fb').text.paragraphs.map((p) => p.justification), ['CENTER', 'LEFT']);
  assertBounds(liveBounds(env, 'fb'), before, 'stays');
});

test('align+: settings and window position are remembered; unit switch converts the gap', () => {
  const root = fs.mkdtempSync(path.join(TMP, 'align-persist-'));
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

test('align+: off-screen saved position falls back to centre', () => {
  const root = fs.mkdtempSync(path.join(TMP, 'align-offscreen-'));
  fs.mkdirSync(path.join(root, 'userData/IllustratorUIScripts'), { recursive: true });
  fs.writeFileSync(path.join(root, 'userData/IllustratorUIScripts/AlignPlus.ini'), 'windowX=5000\nwindowY=100');
  const ini = fs.readFileSync(path.join(root, 'userData/IllustratorUIScripts/AlignPlus.ini'), 'utf8');
  assert.strictEqual(ini.split('\n').length, 2, 'two settings lines');
  let { win } = openPanel({ root, documents: [{}] });
  assert.deepStrictEqual(Array.from(win.location), [100, 100], 'not moved off-screen');
  fs.writeFileSync(path.join(root, 'userData/IllustratorUIScripts/AlignPlus.ini'), 'windowX=640\nwindowY=480');
  ({ win } = openPanel({ root, documents: [{}] }));
  assert.deepStrictEqual(Array.from(win.location), [640, 480], 'on-screen position restored');
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
