'use strict';
const assert = require('assert');
const path = require('path');
const { runScript } = require('./harness');

const SCRIPT = path.join(__dirname, '..', 'scripts', 'COC_Safe Delete_v0.01.jsx');

const tests = [];
const test = (name, fn) => tests.push({ name, fn });

// project: { comps, active, select, aeVersion, ... }
function run(config) {
  return runScript(SCRIPT, Object.assign({ active: 'Main' }, config));
}

function finish(env, opts) {
  assert.deepStrictEqual(env.errors, [], 'strict mock violations');
  const bad = env.alerts.filter((a) => /오류가 발생/.test(a.msg));
  assert.deepStrictEqual(bad, [], 'script reported an error');
  if (!(opts && opts.alerts)) assert.deepStrictEqual(env.alerts, [], 'unexpected alerts');
  const u = env.ae.undo;
  for (let i = 0; i < u.length; i += 2) {
    assert.strictEqual(u[i], 'begin:COC Safe Delete');
    assert.strictEqual(u[i + 1], 'end');
  }
  for (const d of env.dialogs) assert.ok(d.readonly, 'report text must be read-only');
}

const has = (text, part) => assert.ok(text.indexOf(part) !== -1, `expected ${JSON.stringify(part)} in:\n${text}`);
const hasNot = (text, part) => assert.ok(text.indexOf(part) === -1, `did not expect ${JSON.stringify(part)} in:\n${text}`);

const hidden = (name, extra) => Object.assign({ name, kind: 'solid', enabled: false }, extra || {});
const visible = (name, extra) => Object.assign({ name, kind: 'shape' }, extra || {});
const nul = (name, extra) => Object.assign({ name, kind: 'null' }, extra || {});

// deletes the selection, returns [dialog, remaining layer names]
function del(config, opts) {
  const env = run(config);
  const d = env.click(opts);
  finish(env, opts);
  return { env, d, names: env.ae.names(config.active || 'Main') };
}

// ===========================================================================
//  basic behaviour
// ===========================================================================
test('panel: one "Safe Delete" button with a tooltip', () => {
  const env = run({ comps: [{ name: 'Main', layers: [] }] });
  const b = env.button();
  assert.strictEqual(b.text, 'Safe Delete');
  has(b.helpTip, 'Ctrl');
  finish(env);
});

test('palette: running from File > Scripts shows a palette window', () => {
  const env = run({ comps: [{ name: 'Main', layers: [] }], asPalette: true });
  assert.deepStrictEqual(env.log, ['palette shown']);
  finish(env);
});

test('no comp / no selection: explains what to do, changes nothing', () => {
  let env = run({ comps: [{ name: 'Main', layers: [hidden('A')] }], active: null });
  env.click();
  assert.strictEqual(env.alerts.length, 1);
  has(env.alerts[0].msg, '컴포지션');
  assert.deepStrictEqual(env.ae.names('Main'), ['A']);
  finish(env, { alerts: true });

  env = run({ comps: [{ name: 'Main', layers: [hidden('A')] }], select: [] });
  env.click();
  has(env.alerts[0].msg, '선택');
  assert.deepStrictEqual(env.ae.undo, []);
  finish(env, { alerts: true });
});

test('single hidden, unused layer is deleted quietly (no dialog)', () => {
  const r = del({ comps: [{ name: 'Main', layers: [visible('BG'), hidden('Old'), nul('Unused Null')] }], select: ['Old'] });
  assert.strictEqual(r.d, null);
  assert.deepStrictEqual(r.names, ['BG', 'Unused Null']);
  const r2 = del({ comps: [{ name: 'Main', layers: [visible('BG'), nul('Unused Null')] }], select: ['Unused Null'] });
  assert.strictEqual(r2.d, null);
  assert.deepStrictEqual(r2.names, ['BG']);
});

test('visible (eye on) layers of every kind are kept, with their kind', () => {
  const r = del({
    comps: [
      { name: 'Pre', layers: [visible('x')] },
      {
        name: 'Main',
        layers: [
          visible('Shape'), { name: 'Title', kind: 'text' }, { name: 'Logo', kind: 'image' },
          { name: 'Clip', kind: 'footage', audio: false }, { name: 'Solid', kind: 'solid' },
          { name: 'PreLayer', kind: 'precomp', source: 'Pre' }, visible('Guide', { guide: true }),
        ],
      },
    ],
    select: ['Shape', 'Title', 'Logo', 'Clip', 'Solid', 'PreLayer', 'Guide'],
  });
  assert.strictEqual(r.names.length, 7);
  has(r.d.head[0], '7개 중 0개를 삭제했고, 7개는 삭제하지 않았습니다');
  for (const k of ['셰이프', '텍스트', '이미지', '비디오', '솔리드', '프리컴프']) has(r.d.body, `화면에 보이는 ${k} 레이어입니다`);
  has(r.d.body, '(가이드 레이어)');
  has(r.d.body, '[화면 표시]');
});

test('audio: sound on is kept, muted audio-only layer is deleted', () => {
  let r = del({ comps: [{ name: 'Main', layers: [{ name: 'BGM', kind: 'audio' }] }], select: ['BGM'] });
  assert.deepStrictEqual(r.names, ['BGM']);
  has(r.d.body, '[오디오] 오디오 스위치가 켜져 있어 소리가 나는 레이어입니다');
  hasNot(r.d.body, '화면 표시');
  r = del({ comps: [{ name: 'Main', layers: [{ name: 'BGM', kind: 'audio', audio: false }] }], select: ['BGM'] });
  assert.deepStrictEqual(r.names, []);
  // video with the eye off but its sound still on
  r = del({ comps: [{ name: 'Main', layers: [{ name: 'Clip', kind: 'footage', enabled: false }] }], select: ['Clip'] });
  assert.deepStrictEqual(r.names, ['Clip']);
  has(r.d.body, '[오디오]');
});

test('locked layer is kept', () => {
  const r = del({ comps: [{ name: 'Main', layers: [hidden('L', { locked: true })] }], select: ['L'] });
  assert.deepStrictEqual(r.names, ['L']);
  has(r.d.head[0], '삭제하지 않았습니다');
  has(r.d.body, '"L"(#1) — 지우면 아래와 같은 영향이 있습니다');
  has(r.d.body, '[잠금] 잠긴(Lock) 레이어입니다');
});

// ===========================================================================
//  links between layers
// ===========================================================================
test('parent: a null that is the parent of another layer is kept', () => {
  const r = del({ comps: [{ name: 'Main', layers: [nul('Ctrl'), visible('Box', { parent: 'Ctrl' }), visible('Box 2', { parent: 'Ctrl' })] }], select: ['Ctrl'] });
  assert.deepStrictEqual(r.names, ['Ctrl', 'Box', 'Box 2']);
  has(r.d.body, '[부모] "Box"(#2) 레이어의 부모입니다.');
  has(r.d.body, '[부모] "Box 2"(#3) 레이어의 부모입니다.');
});

test('track matte (AE 2023+): any layer used as a matte is kept, with the matte type', () => {
  const r = del({
    comps: [{ name: 'Main', layers: [hidden('Mask'), visible('Other'), visible('Fill', { matte: { layer: 'Mask', type: 'LUMA_INVERTED' } })] }],
    select: ['Mask'],
  });
  assert.deepStrictEqual(r.names, ['Mask', 'Other', 'Fill']);
  has(r.d.body, '[트랙 매트] "Fill"(#3) 레이어의 트랙 매트입니다. (루마 반전 매트)');
});

test('track matte (before 2023): the layer right above a matted layer is kept', () => {
  const comps = [{ name: 'Main', layers: [hidden('Spare'), hidden('Mask'), visible('Fill', { matte: { type: 'ALPHA' } })] }];
  let r = del({ comps, select: ['Mask'], aeVersion: 22 });
  assert.deepStrictEqual(r.names, ['Spare', 'Mask', 'Fill']);
  has(r.d.body, '[트랙 매트] "Fill"(#3) 레이어의 트랙 매트입니다. (알파 매트)');
  r = del({ comps, select: ['Spare'], aeVersion: 22 });
  assert.deepStrictEqual(r.names, ['Mask', 'Fill']);
});

test('effect target: layers picked in an effect (Set Matte, Displacement Map…) are kept', () => {
  const r = del({
    comps: [{
      name: 'Main',
      layers: [
        hidden('Map'), hidden('MatteSrc'),
        visible('Img', {
          effects: [
            { name: 'Displacement Map', matchName: 'ADBE Displacement Map', params: [{ name: 'Displacement Map Layer', layer: 'Map' }] },
            { name: 'Set Matte', matchName: 'ADBE Set Matte3', params: [{ name: 'Take Matte From Layer', layer: 'MatteSrc' }] },
          ],
        }),
      ],
    }],
    select: ['Map', 'MatteSrc'],
  });
  assert.deepStrictEqual(r.names, ['Map', 'MatteSrc', 'Img']);
  has(r.d.body, '[이펙트] "Img"(#3) 레이어의 "Displacement Map" 이펙트 타겟으로 설정되어 있습니다. ("Displacement Map Layer")');
  has(r.d.body, '"Set Matte" 이펙트 타겟으로 설정되어 있습니다');
});

test('effect target: a layer picking itself does not count', () => {
  const r = del({
    comps: [{ name: 'Main', layers: [hidden('Self', { effects: [{ name: 'Displacement Map', params: [{ name: 'Map', layer: 'Self' }] }] })] }],
    select: ['Self'],
  });
  assert.deepStrictEqual(r.names, []);
});

test('environment light source (AE 2024+) is kept', () => {
  const r = del({
    comps: [{ name: 'Main', layers: [{ name: 'Env', kind: 'light', lightSource: 'HDRI' }, hidden('HDRI')] }],
    select: ['HDRI'],
  });
  assert.deepStrictEqual(r.names, ['Env', 'HDRI']);
  has(r.d.body, '[라이트 소스] "Env"(#1) 라이트의 소스 레이어로 쓰이고 있습니다.');
});

// ===========================================================================
//  expressions
// ===========================================================================
test('expression target by name in the same comp', () => {
  const r = del({
    comps: [{
      name: 'Main',
      layers: [nul('Ctrl'), visible('Box', { expr: { 'Transform > Position': 'thisComp.layer("Ctrl").transform.position' } })],
    }],
    select: ['Ctrl'],
  });
  assert.deepStrictEqual(r.names, ['Ctrl', 'Box']);
  has(r.d.body, '[익스프레션] "Box"(#2) 레이어의 "Transform > Position" 프로퍼티 익스프레션의 타겟으로 사용되고 있습니다.');
});

test('expression target from another comp, and the same name in another comp is not a match', () => {
  const comps = [
    { name: 'Main', layers: [nul('Ctrl'), nul('Free')] },
    {
      name: 'Other',
      layers: [
        nul('Free'),
        visible('Reader', {
          expr: {
            'Transform > Opacity': 'comp("Main").layer("Ctrl").effect("Slider Control")("Slider")',
            'Transform > Rotation': 'thisComp.layer("Free").transform.rotation',
          },
        }),
      ],
    },
  ];
  let r = del({ comps, select: ['Ctrl'] });
  assert.deepStrictEqual(r.names, ['Ctrl', 'Free']);
  has(r.d.body, '[익스프레션] [Other] 컴포지션의 "Reader"(#2) 레이어의 "Transform > Opacity" 프로퍼티 익스프레션의 타겟으로 사용되고 있습니다.');
  r = del({ comps, select: ['Free'] });
  assert.deepStrictEqual(r.names, ['Ctrl']);
});

test('expression: comments, strings, regex literals and key .index are not references', () => {
  const r = del({
    comps: [{
      name: 'Main',
      layers: [
        nul('Ctrl'),
        visible('A', {
          expr: {
            'Transform > Position': '// thisComp.layer("Ctrl")\n/* thisComp.layer(1) */ value',
            'Transform > Rotation': 'n = nearestKey(time).index; t = marker.key(1).index; value',
            'Transform > Opacity': 's = "thisComp.layer(\\"Ctrl\\") index numLayers"; r = s.replace(/"\\(/g, \'\'); value',
          },
        }),
      ],
    }],
    select: ['Ctrl'],
  });
  assert.deepStrictEqual(r.names, ['A']);
  assert.strictEqual(r.d, null);
});

test('expression: a regex literal with a quote does not hide a later reference', () => {
  const r = del({
    comps: [{ name: 'Main', layers: [nul('Ctrl'), visible('A', { expr: { 'Transform > Opacity': 'x = "a\'b".replace(/\'/g, ""); thisComp.layer(\'Ctrl\').transform.opacity' } })] }],
    select: ['Ctrl'],
  });
  assert.deepStrictEqual(r.names, ['Ctrl', 'A']);
  has(r.d.body, '타겟으로 사용되고 있습니다');
});

test('expression: layer("name") means the topmost layer with that name', () => {
  const comps = [{
    name: 'Main',
    layers: [nul('Null 1'), visible('A', { expr: { 'Transform > Position': 'thisComp.layer("Null 1").position' } }), nul('Null 1')],
  }];
  let r = del({ comps, select: [3] });
  assert.deepStrictEqual(r.names, ['Null 1', 'A']);
  assert.strictEqual(r.d, null);
  r = del({ comps, select: [1] });
  assert.deepStrictEqual(r.names, ['Null 1', 'A', 'Null 1']);
});

test('expression: a comp held in a variable still counts', () => {
  let r = del({
    comps: [{ name: 'Main', layers: [nul('Ctrl'), visible('A', { expr: { 'Transform > Position': 'var c = thisComp;\nc.layer("Ctrl").position' } })] }],
    select: ['Ctrl'],
  });
  assert.deepStrictEqual(r.names, ['Ctrl', 'A']);
  r = del({
    comps: [
      { name: 'Main', layers: [nul('Ctrl')] },
      { name: 'Other', layers: [visible('A', { expr: { 'Transform > Position': 'var c = comp("Main");\nc.layer("Ctrl").position' } })] },
    ],
    select: ['Ctrl'],
  });
  assert.deepStrictEqual(r.names, ['Ctrl']);
  has(r.d.body, '[Other] 컴포지션의');
});

test('expression: reaching into a precomp through .source', () => {
  const r = del({
    comps: [
      { name: 'Pre', layers: [nul('Inner'), visible('Art')] },
      {
        name: 'Main',
        layers: [
          { name: 'Pre', kind: 'precomp', source: 'Pre' },
          visible('Follower', { expr: { 'Transform > Position': 'thisComp.layer("Pre").source.layer("Inner").transform.position' } }),
        ],
      },
    ],
    active: 'Pre',
    select: ['Inner'],
  });
  assert.deepStrictEqual(r.names, ['Inner', 'Art']);
  has(r.d.body, '[Main] 컴포지션의 "Follower"(#2) 레이어의 "Transform > Position" 프로퍼티 익스프레션의 타겟');
});

test('expression: numeric layer(n) is the target, or shifts when a layer above it goes', () => {
  const layers = [
    visible('Top'), hidden('H2'), hidden('H3'), visible('Abs', { expr: { 'Transform > Opacity': 'thisComp.layer(3).transform.opacity' } }),
    hidden('H5'),
  ];
  let r = del({ comps: [{ name: 'Main', layers }], select: ['H3'] });
  has(r.d.body, '[익스프레션] "Abs"(#4) 레이어의 "Transform > Opacity" 프로퍼티 익스프레션의 타겟으로 사용되고 있습니다. (layer(3) 번호로 참조)');
  r = del({ comps: [{ name: 'Main', layers }], select: ['H2'] });
  has(r.d.body, 'layer(3) 처럼 번호로 레이어를 가리키고 있어, 지우면 번호가 밀려 다른 레이어를 가리키게 됩니다.');
  r = del({ comps: [{ name: 'Main', layers }], select: ['H5'] });
  assert.deepStrictEqual(r.names, ['Top', 'H2', 'H3', 'Abs']);
});

test('expression: relative layer(index-1) / layer(thisLayer, k)', () => {
  const layers = [
    hidden('H1'), hidden('H2'), hidden('H3'),
    visible('Follow', { expr: { 'Transform > Position': 'thisComp.layer(index - 1).transform.position' } }),
    visible('Far', { expr: { 'Transform > Rotation': 'thisComp.layer(thisLayer, -4).transform.rotation' } }),
    hidden('H6'),
  ];
  const go = (sel) => del({ comps: [{ name: 'Main', layers }], select: sel });
  let r = go(['H3']);
  has(r.d.body, '"Follow"(#4) 레이어의 "Transform > Position" 프로퍼티 익스프레션의 타겟으로 사용되고 있습니다. (layer(index-1) 상대 번호로 참조)');
  // H2 is between "Far"(5) and its target H1(1): the target would change
  r = go(['H2']);
  assert.deepStrictEqual(r.names, ['H1', 'H2', 'H3', 'Follow', 'Far', 'H6']);
  has(r.d.body, '"Far"(#5) 레이어의 "Transform > Rotation" 프로퍼티 익스프레션이 layer(index-4) 처럼 상대 번호로 레이어를 가리키고 있어');
  hasNot(r.d.body, 'Follow');
  // H6 is below everything that uses a relative reference
  r = go(['H6']);
  assert.strictEqual(r.d, null);
});

test('expression: own index / other layer index / numLayers / computed layer()', () => {
  const layers = [
    hidden('H1'),
    visible('Stagger', { expr: { 'Transform > Position': 'delay = (index - 1) * 0.1; value' } }),
    visible('Idx', { expr: { 'Transform > Rotation': 'thisComp.layer("Stagger").index * 10' } }),
    hidden('H4'),
  ];
  let r = del({ comps: [{ name: 'Main', layers }], select: ['H1'] });
  has(r.d.body, '"Stagger"(#2) 레이어의 "Transform > Position" 프로퍼티 익스프레션이 자기 레이어 번호(index)를 쓰고 있어');
  has(r.d.body, '"Idx"(#3) 레이어의 "Transform > Rotation" 프로퍼티 익스프레션이 "Stagger" 레이어의 번호(index)를 쓰고 있어');
  r = del({ comps: [{ name: 'Main', layers }], select: ['H4'] });
  assert.strictEqual(r.d, null);

  r = del({ comps: [{ name: 'Main', layers: [hidden('H1'), visible('Count', { expr: { 'Transform > Opacity': 'thisComp.numLayers * 5' } })] }], select: ['H1'] });
  has(r.d.body, '레이어 개수(numLayers)를 쓰고 있어');
  r = del({
    comps: [{ name: 'Main', layers: [visible('Pick', { expr: { 'Transform > Position': 'i = Math.round(effect("Pick")("Slider"));\nthisComp.layer(i).position' } }), hidden('H2')] }],
    select: ['H2'],
  });
  has(r.d.body, '계산한 값으로 레이어를 찾고 있어');
});

test('expression: switched-off expressions still count, and say so', () => {
  const r = del({
    comps: [{ name: 'Main', layers: [nul('Ctrl'), visible('A', { expr: { 'Transform > Position': 'thisComp.layer("Ctrl").position' }, exprOff: ['Transform > Position'] })] }],
    select: ['Ctrl'],
  });
  has(r.d.body, '(지금은 꺼져 있는 익스프레션)');
});

test('expression inside an effect parameter', () => {
  const r = del({
    comps: [{
      name: 'Main',
      layers: [nul('Ctrl'), visible('A', { effects: [{ name: 'Glow', params: [{ name: 'Radius', expression: 'thisComp.layer("Ctrl").effect("R")("Slider")' }] }] })],
    }],
    select: ['Ctrl'],
  });
  has(r.d.body, '"A"(#2) 레이어의 "Effects > Glow > Radius" 프로퍼티 익스프레션의 타겟으로 사용되고 있습니다.');
});

// ===========================================================================
//  layers that change how other layers look
// ===========================================================================
test('adjustment layer: kept only when it has an effect on and something visible below', () => {
  const fx = [{ name: 'Curves', params: [] }];
  let r = del({ comps: [{ name: 'Main', layers: [{ name: 'Adj', kind: 'adjustment', effects: fx }, visible('Art')] }], select: ['Adj'] });
  assert.deepStrictEqual(r.names, ['Adj', 'Art']);
  has(r.d.body, '[조정 레이어] 이펙트가 켜진 조정 레이어로, 아래 레이어 1개("Art"(#2))의 모습을 바꾸고 있습니다.');
  hasNot(r.d.body, '화면 표시');
  r = del({ comps: [{ name: 'Main', layers: [{ name: 'Adj', kind: 'adjustment' }, visible('Art')] }], select: ['Adj'] });
  assert.deepStrictEqual(r.names, ['Art']);
  r = del({ comps: [{ name: 'Main', layers: [visible('Art'), { name: 'Adj', kind: 'adjustment', effects: fx }] }], select: ['Adj'] });
  assert.deepStrictEqual(r.names, ['Art']);
  r = del({ comps: [{ name: 'Main', layers: [{ name: 'Adj', kind: 'adjustment', effects: [{ name: 'Curves', enabled: false }] }, visible('Art')] }], select: ['Adj'] });
  assert.deepStrictEqual(r.names, ['Art']);
  // does not overlap in time
  r = del({ comps: [{ name: 'Main', layers: [{ name: 'Adj', kind: 'adjustment', effects: fx, inPoint: 0, outPoint: 2 }, visible('Art', { inPoint: 5, outPoint: 8 })] }], select: ['Adj'] });
  assert.deepStrictEqual(r.names, ['Art']);
});

test('camera: kept while it is the camera 3D layers are seen through', () => {
  let r = del({ comps: [{ name: 'Main', layers: [{ name: 'Cam', kind: 'camera' }, visible('Card', { threeD: true })] }], select: ['Cam'] });
  assert.deepStrictEqual(r.names, ['Cam', 'Card']);
  has(r.d.body, '[카메라] 컴포지션 카메라로서 3D 레이어 1개("Card"(#2))의 시점을 정하고 있습니다.');
  r = del({ comps: [{ name: 'Main', layers: [{ name: 'Cam', kind: 'camera' }, visible('Flat')] }], select: ['Cam'] });
  assert.deepStrictEqual(r.names, ['Flat']);
  // a camera above covers the whole time → the lower one is never used
  const two = (topOut) => ({ comps: [{ name: 'Main', layers: [{ name: 'Cam A', kind: 'camera', outPoint: topOut }, { name: 'Cam B', kind: 'camera' }, visible('Card', { threeD: true })] }], select: ['Cam B'] });
  r = del(two(10));
  assert.deepStrictEqual(r.names, ['Cam A', 'Card']);
  r = del(two(5));
  assert.deepStrictEqual(r.names, ['Cam A', 'Cam B', 'Card']);
});

test('light: kept while it lights a 3D layer', () => {
  let r = del({ comps: [{ name: 'Main', layers: [{ name: 'Key', kind: 'light' }, visible('Card', { threeD: true })] }], select: ['Key'] });
  assert.deepStrictEqual(r.names, ['Key', 'Card']);
  has(r.d.body, '[라이트] 라이트로서 3D 레이어 1개("Card"(#2))를 비추고 있습니다.');
  r = del({ comps: [{ name: 'Main', layers: [{ name: 'Key', kind: 'light' }, visible('Card', { threeD: true, acceptsLights: 0 })] }], select: ['Key'] });
  assert.deepStrictEqual(r.names, ['Card']);
  r = del({ comps: [{ name: 'Main', layers: [{ name: 'Key', kind: 'light', enabled: false }, visible('Card', { threeD: true })] }], select: ['Key'] });
  assert.deepStrictEqual(r.names, ['Card']);
});

test('solo: the only soloed layer is kept, unless another solo layer stays', () => {
  let r = del({ comps: [{ name: 'Main', layers: [hidden('S', { solo: true }), visible('A'), visible('B')] }], select: ['S'] });
  assert.deepStrictEqual(r.names, ['S', 'A', 'B']);
  has(r.d.body, '[솔로] 솔로(Solo)가 켜진 레이어입니다. 지우면 솔로가 풀려 숨어 있던 레이어 2개가 다시 보이게 됩니다.');
  r = del({ comps: [{ name: 'Main', layers: [hidden('S', { solo: true }), visible('A', { solo: true }), visible('B')] }], select: ['S'] });
  assert.deepStrictEqual(r.names, ['A', 'B']);
});

// ===========================================================================
//  essential graphics
// ===========================================================================
test('essential graphics: a property used as a master property is kept (instance in another comp)', () => {
  const r = del({
    comps: [
      { name: 'Tpl', layers: [nul('Ctrl'), hidden('Spare')], egp: [{ layer: 'Ctrl', prop: 'Transform > Position', name: 'Logo Position' }] },
      { name: 'Main', layers: [{ name: 'Tpl', kind: 'precomp', source: 'Tpl' }] },
    ],
    active: 'Tpl',
    select: ['Ctrl', 'Spare'],
  });
  assert.deepStrictEqual(r.names, ['Ctrl']);
  has(r.d.body, '[에센셜 그래픽스] 이 레이어의 "Transform > Position" 프로퍼티가 에센셜 그래픽스 패널에 "Logo Position" (마스터 프로퍼티)로 등록되어 있습니다.');
  assert.strictEqual(r.env.counts.compsAdded, 0);
});

test('essential graphics: comp not used anywhere is checked through a temporary comp that is removed again', () => {
  const r = del({
    comps: [{ name: 'Tpl', layers: [hidden('Photo')], egp: [{ layer: 'Photo', name: 'Replace Me' }] }],
    active: 'Tpl',
    select: ['Photo'],
  });
  assert.deepStrictEqual(r.names, ['Photo']);
  has(r.d.body, '이 레이어가 에센셜 그래픽스 패널에 "Replace Me" (미디어 교체)로 등록되어 있습니다.');
  assert.strictEqual(r.env.counts.compsAdded, 1);
  assert.deepStrictEqual(r.env.ae.items(), ['Tpl']);
});

// ===========================================================================
//  several layers at once
// ===========================================================================
test('several layers: summary with deleted / kept lists', () => {
  const r = del({
    comps: [{ name: 'Main', layers: [hidden('Old 1'), nul('Ctrl'), visible('Box', { parent: 'Ctrl' }), hidden('Old 2'), visible('Logo')] }],
    select: ['Old 1', 'Ctrl', 'Old 2', 'Logo'],
  });
  assert.deepStrictEqual(r.names, ['Ctrl', 'Box', 'Logo']);
  assert.deepStrictEqual(r.d.head, ['선택한 레이어 4개 중 2개를 삭제했고, 2개는 삭제하지 않았습니다.']);
  has(r.d.body, '■ 삭제함 (2)\n    - "Old 1"\n    - "Old 2"');
  // numbers are the ones after deleting
  has(r.d.body, '■ 삭제하지 않음 (2)\n    - "Ctrl"(#1)\n        • [부모] "Box"(#2) 레이어의 부모입니다.\n    - "Logo"(#3)\n        • [화면 표시]');
  hasNot(r.d.body, '※');
});

test('several layers: links between layers deleted together are fine', () => {
  const r = del({
    comps: [{
      name: 'Main',
      layers: [nul('Ctrl'), hidden('Child', { parent: 'Ctrl', expr: { 'Transform > Position': 'thisComp.layer("Ctrl").position' } }), hidden('Mask'), hidden('Fill', { matte: { layer: 'Mask' } }), visible('Keep')],
    }],
    select: ['Ctrl', 'Child', 'Mask', 'Fill'],
  });
  assert.deepStrictEqual(r.names, ['Keep']);
  has(r.d.head[0], '4개 중 4개를 삭제했고, 0개는 삭제하지 않았습니다');
  has(r.d.body, '※ 함께 선택해서 같이 지운 레이어끼리의 연결');
});

test('several layers: a kept layer keeps what it depends on (chain)', () => {
  const r = del({
    comps: [{ name: 'Main', layers: [nul('A'), nul('B', { parent: 'A' }), visible('V', { parent: 'B' })] }],
    select: ['A', 'B'],
  });
  assert.deepStrictEqual(r.names, ['A', 'B', 'V']);
  has(r.d.body, '"A"(#1)\n        • [부모] "B"(#2) 레이어의 부모입니다.');
  has(r.d.body, '"B"(#2)\n        • [부모] "V"(#3) 레이어의 부모입니다.');
});

test('windows line breaks in the report', () => {
  const env = run({ os: 'win', comps: [{ name: 'Main', layers: [visible('A'), visible('B')] }], select: ['A', 'B'] });
  const d = env.click();
  assert.ok(/\r\n/.test(d.body));
  finish(env);
});

// ===========================================================================
//  Ctrl + click: reason tags in the names of kept layers
// ===========================================================================
test('ctrl+click: kept layers get reason tags, deleted ones are gone', () => {
  const comps = [{
    name: 'Main',
    layers: [
      nul('Ctrl'), hidden('Mask'), hidden('Map'),
      visible('Box', {
        parent: 'Ctrl', matte: { layer: 'Mask' },
        expr: { 'Transform > Position': 'thisComp.layer("Ctrl").position' },
        effects: [{ name: 'Set Matte', params: [{ name: 'Take Matte From Layer', layer: 'Map' }, { name: 'Other', layer: 'Mask' }] }],
      }),
      hidden('Junk'),
    ],
  }];
  const env = run({ comps, select: ['Ctrl', 'Mask', 'Map', 'Box', 'Junk'] });
  const d = env.click({ ctrl: true });
  finish(env);
  assert.deepStrictEqual(env.ae.names('Main'), [
    'Ctrl (#Parent)(#Exp_Target)', 'Mask (#Matte)(#Set Matte fx)', 'Map (#Set Matte fx)', 'Box (#Visible)']);
  has(d.head.join('\n'), '이유 태그를 붙였습니다');
  // AE updated the expression to the new name, so the link still works
  assert.strictEqual(env.ae.expression('Main', 'Box (#Visible)', 'Transform > Position'), 'thisComp.layer("Ctrl (#Parent)(#Exp_Target)").position');
  // the report uses the names from before the tags
  has(d.body, '- "Ctrl"(#1)');
});

test('ctrl+click again replaces old tags instead of adding more; Cmd works too', () => {
  const env = run({ comps: [{ name: 'Main', layers: [nul('Ctrl'), visible('Box', { parent: 'Ctrl' })] }], select: ['Ctrl'] });
  env.click({ ctrl: true });
  assert.deepStrictEqual(env.ae.names('Main'), ['Ctrl (#Parent)', 'Box']);
  env.ae.select([1]);
  env.click({ cmd: true });
  assert.deepStrictEqual(env.ae.names('Main'), ['Ctrl (#Parent)', 'Box']);
  finish(env);
});

test('ctrl+click: locked layers are tagged and locked again; plain click never renames', () => {
  const env = run({ comps: [{ name: 'Main', layers: [hidden('L', { locked: true })] }], select: ['L'] });
  env.click();
  assert.deepStrictEqual(env.ae.names('Main'), ['L']);
  env.click({ ctrl: true });
  assert.deepStrictEqual(env.ae.names('Main'), ['L (#Locked)']);
  assert.strictEqual(env.ae.layer('Main', 'L (#Locked)').locked, true);
  finish(env);
});

test('ctrl+click: if AE would not follow the rename in expressions, the name is left alone', () => {
  const env = run({
    autoUpdateExpressions: false,
    comps: [{ name: 'Main', layers: [nul('Ctrl'), nul('P'), visible('Box', { parent: 'P', expr: { 'Transform > Position': 'thisComp.layer("Ctrl").position' } })] }],
    select: ['Ctrl', 'P'],
  });
  const d = env.click({ ctrl: true });
  finish(env);
  assert.deepStrictEqual(env.ae.names('Main'), ['Ctrl', 'P (#Parent)', 'Box']);
  has(d.body, '태그를 붙이지 않은 레이어: "Ctrl"(#1)');
});

// ===========================================================================
let failed = 0;
for (const t of tests) {
  try {
    t.fn();
    console.log(`  ok  ${t.name}`);
  } catch (e) {
    failed++;
    console.log(`FAIL  ${t.name}\n      ${String(e.stack || e).split('\n').slice(0, 6).join('\n      ')}`);
  }
}
console.log(`\n${tests.length - failed}/${tests.length} passed`);
process.exit(failed ? 1 : 0);
