'use strict';
/*
 * Mock ExtendScript runtime for After Effects ScriptUI panels:
 *  - an ES3-ish VM realm (ES5+ builtins removed so accidental use throws)
 *  - a small strict ScriptUI mock (Panel host, palette/dialog windows, buttons, texts)
 *  - a strict After Effects DOM mock: project items, comps, layers, property trees with
 *    expressions and layer-index parameters, parenting, track mattes (legacy and 23.0+),
 *    essential properties, layer removal and renaming
 * Every access to a DOM object returns a fresh wrapper (like AE), unknown properties throw,
 * and a removed layer throws "Object is invalid" on any access.
 */
const vm = require('vm');
const fs = require('fs');

// ---------------------------------------------------------------------------
// ES3 realm
// ---------------------------------------------------------------------------
const STRIP = `
(function () {
  var i;
  function strip(obj, names) { for (i = 0; i < names.length; i++) { try { delete obj[names[i]]; } catch (e) {} } }
  strip(Array.prototype, ['forEach','map','filter','reduce','reduceRight','some','every','indexOf','lastIndexOf','find','findIndex','findLast','findLastIndex','includes','fill','flat','flatMap','entries','keys','values','at','copyWithin','toSorted','toReversed','toSpliced','with']);
  strip(Array, ['isArray','from','of']);
  strip(String.prototype, ['trim','trimStart','trimEnd','trimLeft','trimRight','includes','startsWith','endsWith','padStart','padEnd','repeat','codePointAt','normalize','at','replaceAll','matchAll','isWellFormed','toWellFormed']);
  strip(String, ['fromCodePoint','raw']);
  strip(Object, ['keys','create','defineProperty','defineProperties','getPrototypeOf','getOwnPropertyNames','getOwnPropertyDescriptor','getOwnPropertyDescriptors','freeze','seal','isFrozen','isSealed','assign','entries','values','fromEntries','is','setPrototypeOf','preventExtensions','isExtensible','groupBy','hasOwn']);
  strip(Function.prototype, ['bind']);
  strip(Date, ['now']);
  strip(Date.prototype, ['toISOString','toJSON']);
  strip(Number, ['isNaN','isFinite','isInteger','isSafeInteger','parseFloat','parseInt','EPSILON','MAX_SAFE_INTEGER','MIN_SAFE_INTEGER']);
  strip(Math, ['trunc','sign','cbrt','log10','log2','log1p','expm1','hypot','fround','imul','clz32','sinh','cosh','tanh','asinh','acosh','atanh']);
  strip(this, ['JSON','Promise','Map','Set','WeakMap','WeakSet','WeakRef','Symbol','Proxy','Reflect','BigInt','ArrayBuffer','SharedArrayBuffer','DataView','Int8Array','Uint8Array','Uint8ClampedArray','Int16Array','Uint16Array','Int32Array','Uint32Array','Float32Array','Float64Array','BigInt64Array','BigUint64Array','Intl','Atomics','FinalizationRegistry','AggregateError','globalThis','queueMicrotask','structuredClone','WebAssembly']);
})();
`;

function createRealm() {
  const ctx = vm.createContext({});
  const VArray = vm.runInContext('Array', ctx);
  vm.runInContext(STRIP, ctx);
  const varr = (list) => {
    const a = new VArray();
    for (const x of list || []) a.push(x);
    return a;
  };
  return { ctx, varr };
}

// ---------------------------------------------------------------------------
// strict wrapper
// ---------------------------------------------------------------------------
const PASSTHROUGH = new Set(['toString', 'valueOf', 'constructor', 'toJSON', 'inspect', 'then', 'hasOwnProperty',
  'isPrototypeOf', 'propertyIsEnumerable', 'toLocaleString', '__proto__', 'toSource']);

// proto: prototype for instanceof; props: { name: { get, set } }; invalid(): true when the object is gone
function makeObject(env, label, proto, props, invalid) {
  const target = Object.create(proto || Object.prototype);
  for (const [k, d] of Object.entries(props)) {
    Object.defineProperty(target, k, {
      get: d.get || (() => d.value),
      set: d.set || (() => { throw new Error(`${label}.${k} is read-only`); }),
      enumerable: true,
    });
  }
  return new Proxy(target, {
    get(t, prop, recv) {
      if (typeof prop === 'symbol' || PASSTHROUGH.has(prop)) return Reflect.get(t, prop, recv);
      if (invalid && invalid()) throw new Error(`${label}: Object is invalid`);
      if (!Object.prototype.hasOwnProperty.call(props, prop)) {
        const msg = `[${label}] read of unknown property '${String(prop)}'`;
        env.errors.push(msg);
        throw new Error(msg);
      }
      return Reflect.get(t, prop, recv);
    },
    set(t, prop, value, recv) {
      if (invalid && invalid()) throw new Error(`${label}: Object is invalid`);
      if (typeof prop === 'symbol' || !Object.prototype.hasOwnProperty.call(props, prop)) {
        const msg = `[${label}] write of unknown property '${String(prop)}'`;
        env.errors.push(msg);
        throw new Error(msg);
      }
      return Reflect.set(t, prop, value, recv);
    },
  });
}

function strictEnum(env, name, members) {
  return new Proxy(Object.assign({}, members), {
    get(t, prop) {
      if (typeof prop === 'symbol' || PASSTHROUGH.has(prop)) return t[prop];
      if (!(prop in t)) {
        const msg = `[${name}] unknown enum member '${String(prop)}'`;
        env.errors.push(msg);
        throw new Error(msg);
      }
      return t[prop];
    },
  });
}

// ---------------------------------------------------------------------------
// ScriptUI mock
// ---------------------------------------------------------------------------
function makeScriptUI(env) {
  function Panel() {}
  function Window(type, title, bounds, props) {
    if (!['dialog', 'palette', 'window'].includes(type)) throw new Error('bad window type ' + type);
    if (bounds !== undefined) throw new Error('mock expects window bounds undefined');
    return control(type, null, title, props);
  }

  const CONTROL_TYPES = new Set(['button', 'statictext', 'edittext', 'group', 'panel']);

  function control(type, parent, text, props, host) {
    if (text !== undefined && typeof text !== 'string') throw new Error(`ScriptUI: non-string text for ${type}`);
    const st = { type, text: text || '', props: props || {}, parent, children: [], closed: false, result: undefined };
    const plain = ['helpTip', 'onClick', 'alignment', 'alignChildren', 'orientation', 'margins', 'spacing',
      'defaultElement', 'cancelElement', 'onResizing', 'onResize', 'enabled', 'visible', 'onShow', 'onClose'];
    const def = {
      type: { value: type },
      text: { get: () => st.text, set: (v) => { if (typeof v !== 'string') throw new Error('text must be a string'); st.text = v; } },
      properties: { value: st.props },
      parent: { get: () => st.parent },
      children: { get: () => env.varr(st.children) },
      preferredSize: { get: () => st.preferredSize || { width: 0, height: 0 }, set: (v) => { st.preferredSize = v; } },
      layout: { value: { layout() {}, resize() {} } },
      add: {
        value(childType, bounds, childText, childProps) {
          if (!CONTROL_TYPES.has(childType)) throw new Error('ScriptUI mock: unknown control ' + childType);
          if (bounds !== undefined) throw new Error('mock expects bounds undefined');
          const c = control(childType, proxy, childText, childProps);
          st.children.push(c);
          return c;
        },
      },
      _state: { value: st },
    };
    for (const k of plain) def[k] = { get: () => st[k], set: (v) => { st[k] = v; } };
    const isWin = ['dialog', 'palette', 'window'].includes(type);
    if (isWin) {
      def.show = {
        value() {
          if (type !== 'dialog') {
            env.log.push('palette shown');
            return undefined;
          }
          const report = {
            head: st.children.filter((c) => c._state.type === 'statictext').map((c) => c._state.text),
            body: st.children.filter((c) => c._state.type === 'edittext').map((c) => c._state.text).join('\n'),
            readonly: st.children.filter((c) => c._state.type === 'edittext').every((c) => c._state.props.readonly === true),
          };
          env.dialogs.push(report);
          // press the OK button
          const ok = findButton(proxy, 'ok');
          if (!ok) throw new Error('dialog without an ok button');
          if (typeof ok.onClick === 'function') ok.onClick();
          if (!st.closed) throw new Error('ok button did not close the dialog');
          return st.result;
        },
      };
      def.close = { value(r) { st.closed = true; st.result = r === undefined ? 0 : r; } };
      def.center = { value() {} };
    }
    const proto = host ? Panel.prototype : (isWin ? Window.prototype : Object.prototype);
    const proxy = makeObject(env, `ScriptUI ${type}`, proto, def);
    return proxy;
  }

  function findButton(win, name) {
    const stack = [win];
    while (stack.length) {
      const c = stack.pop();
      if (c._state.type === 'button' && c._state.props.name === name) return c;
      for (const k of c._state.children) stack.push(k);
    }
    return null;
  }

  const keyboardState = { ctrlKey: false, metaKey: false, shiftKey: false, altKey: false };
  const ScriptUI = { environment: { keyboardState } };
  return { Panel, Window, ScriptUI, keyboardState, makePanel: () => control('panel', null, '', {}, true) };
}

// ---------------------------------------------------------------------------
// After Effects DOM mock
// ---------------------------------------------------------------------------
function makeAE(env) {
  const cfg = env.config;
  const version = cfg.aeVersion || 25;
  const E = {
    PropertyType: strictEnum(env, 'PropertyType', { PROPERTY: 6812, INDEXED_GROUP: 6813, NAMED_GROUP: 6814 }),
    PropertyValueType: strictEnum(env, 'PropertyValueType', { NO_VALUE: 6412, ThreeD_SPATIAL: 6413, ThreeD: 6414,
      TwoD_SPATIAL: 6415, TwoD: 6416, OneD: 6417, COLOR: 6418, CUSTOM_VALUE: 6419, MARKER: 6420, LAYER_INDEX: 6421,
      MASK_INDEX: 6422, SHAPE: 6423, TEXT_DOCUMENT: 6424 }),
    TrackMatteType: strictEnum(env, 'TrackMatteType', { NO_TRACK_MATTE: 5012, ALPHA: 5013, ALPHA_INVERTED: 5014,
      LUMA: 5015, LUMA_INVERTED: 5016 }),
  };

  class Item {}
  class CompItem extends Item {}
  class FootageItem extends Item {}
  class SolidSource {}
  class FileSource {}
  class Layer {}
  class AVLayer extends Layer {}
  class ShapeLayer extends AVLayer {}
  class TextLayer extends AVLayer {}
  class CameraLayer extends Layer {}
  class LightLayer extends Layer {}
  class PropertyBase {}
  class Property extends PropertyBase {}
  class PropertyGroup extends PropertyBase {}
  const classes = { Item, CompItem, FootageItem, SolidSource, FileSource, Layer, AVLayer, ShapeLayer, TextLayer,
    CameraLayer, LightLayer, PropertyBase, Property, PropertyGroup };

  let nextId = 100;
  const project = { items: [], active: null, undo: [], selection: [] };

  // ----- nodes --------------------------------------------------------------
  function newComp(spec) {
    return { kind: 'comp', id: nextId++, name: spec.name, duration: spec.duration || 10, layers: [], egp: [],
      width: 1920, height: 1080, pixelAspect: 1, frameRate: 30, removed: false, spec };
  }
  function newFootage(name, main) {
    return { kind: 'footage', id: nextId++, name, main, removed: false };
  }

  function group(name, matchName, parent, extra) {
    return Object.assign({ isGroup: true, name, matchName, parent, children: [] }, extra || {});
  }
  function prop(name, matchName, parent, extra) {
    return Object.assign({ isGroup: false, name, matchName, parent, valueType: E.PropertyValueType.OneD, value: 0,
      expression: '', expressionEnabled: true, canSetExpression: true }, extra || {});
  }
  function addChild(parent, child) {
    child.parent = parent;
    parent.children.push(child);
    return child;
  }

  function layerKind(spec) { return spec.kind || 'solid'; }

  function buildLayer(comp, spec) {
    const kind = layerKind(spec);
    const L = {
      kind: 'layer', lkind: kind, comp, spec, name: spec.name, removed: false,
      locked: !!spec.locked, solo: !!spec.solo, threeD: !!spec.threeD, guide: !!spec.guide,
      adjustment: kind === 'adjustment' || !!spec.adjustment,
      inPoint: spec.inPoint !== undefined ? spec.inPoint : 0,
      outPoint: spec.outPoint !== undefined ? spec.outPoint : comp.duration,
      parent: null, matteLayer: null, matteType: E.TrackMatteType.NO_TRACK_MATTE, lightSource: null,
      source: null, isGroup: true, children: [], matchName: '',
    };
    const visual = !['null', 'camera', 'light', 'audio'].includes(kind);
    L.enabled = spec.enabled !== undefined ? spec.enabled : (kind === 'audio' || kind === 'null' ? false : true);
    L.hasVideo = ['camera', 'light', 'audio'].includes(kind) ? false : true;
    L.nullLayer = kind === 'null';
    L.hasAudio = kind === 'audio' || kind === 'footage' || !!spec.hasAudio;
    L.audioEnabled = spec.audio !== undefined ? !!spec.audio : L.hasAudio;
    if (kind === 'camera') L.matchName = 'ADBE Camera Layer';
    else if (kind === 'light') L.matchName = 'ADBE Light Layer';
    else if (kind === 'text') L.matchName = 'ADBE Text Layer';
    else if (kind === 'shape') L.matchName = 'ADBE Vector Layer';
    else L.matchName = 'ADBE AV Layer';

    if (kind === 'text') {
      const t = addChild(L, group('Text', 'ADBE Text Properties', L));
      addChild(t, prop('Source Text', 'ADBE Text Document', t, { valueType: E.PropertyValueType.TEXT_DOCUMENT }));
    }
    const tr = addChild(L, group('Transform', 'ADBE Transform Group', L));
    for (const [n, mn] of [['Anchor Point', 'ADBE Anchor Point'], ['Position', 'ADBE Position'], ['Scale', 'ADBE Scale'],
      ['Rotation', 'ADBE Rotate Z'], ['Opacity', 'ADBE Opacity']]) {
      addChild(tr, prop(n, mn, tr));
    }
    if (kind !== 'camera' && kind !== 'light') {
      const fx = addChild(L, group('Effects', 'ADBE Effect Parade', L));
      for (const ef of spec.effects || []) {
        const g = addChild(fx, group(ef.name, ef.matchName || 'ADBE Slider Control', fx, { enabled: ef.enabled !== false }));
        for (const p of ef.params || []) {
          const pp = addChild(g, prop(p.name, p.matchName || 'ADBE Param', g));
          if (p.layer !== undefined) {
            pp.valueType = E.PropertyValueType.LAYER_INDEX;
            pp.layerRefName = p.layer;
            pp.canSetExpression = false;
          }
          if (p.expression) pp.expression = p.expression;
          if (p.expressionEnabled === false) pp.expressionEnabled = false;
        }
      }
    }
    if (visual) {
      const mo = addChild(L, group('Material Options', 'ADBE Material Options Group', L));
      addChild(mo, prop('Accepts Lights', 'ADBE Accepts Lights', mo, { value: spec.acceptsLights === 0 ? 0 : 1 }));
    }
    if (kind === 'light') {
      const lo = addChild(L, group('Light Options', 'ADBE Light Options Group', L));
      addChild(lo, prop('Intensity', 'ADBE Light Intensity', lo, { value: 100 }));
    }
    addChild(L, prop('Marker', 'ADBE Marker', L, { valueType: E.PropertyValueType.MARKER, canSetExpression: false }));
    for (const [path, code] of Object.entries(spec.expr || {})) {
      const p = findPath(L, path);
      if (!p) throw new Error(`mock: no property ${path} on ${spec.name}`);
      p.expression = code;
      if ((spec.exprOff || []).includes(path)) p.expressionEnabled = false;
    }
    return L;
  }

  function findPath(root, path) {
    let node = root;
    for (const part of path.split(' > ')) {
      node = (node.children || []).find((c) => c.name === part);
      if (!node) return null;
    }
    return node;
  }

  function sourceFor(spec) {
    const kind = layerKind(spec);
    if (kind === 'precomp') {
      const c = project.items.find((it) => it.kind === 'comp' && it.name === spec.source);
      if (!c) throw new Error('mock: no comp ' + spec.source);
      return c;
    }
    if (['solid', 'null', 'adjustment'].includes(kind)) return newFootage(spec.name, { solid: true });
    if (kind === 'image') return newFootage(spec.name, { still: true });
    if (kind === 'footage' || kind === 'audio') return newFootage(spec.name, { still: false });
    return null;
  }

  function layerIndex(L) { return L.comp.layers.indexOf(L) + 1; }

  function resolveName(comp, ref) {
    if (typeof ref === 'number') return comp.layers[ref - 1];
    const L = comp.layers.find((l) => l.name === ref);
    if (!L) throw new Error(`mock: no layer '${ref}' in ${comp.name}`);
    return L;
  }

  function walkNodes(node, fn) {
    fn(node);
    for (const c of node.children || []) walkNodes(c, fn);
  }

  // ----- facades ------------------------------------------------------------
  function propDepth(node) {
    let d = 0;
    for (let n = node; n && n.kind !== 'layer'; n = n.parent) d++;
    return d;
  }

  function nodeFacade(node) {
    if (node.kind === 'layer') return layerFacade(node);
    return propFacade(node);
  }

  function childAccess(node) {
    return {
      numProperties: { get: () => node.children.length },
      property: {
        value(key) {
          let c;
          if (typeof key === 'number') c = node.children[key - 1];
          else c = node.children.find((x) => x.matchName === key || x.name === key);
          return c ? propFacade(c) : null;
        },
      },
    };
  }

  function propFacade(node) {
    const layer = () => { let n = node; while (n.kind !== 'layer') n = n.parent; return n; };
    const common = {
      name: { get: () => node.name },
      matchName: { get: () => node.matchName },
      propertyDepth: { get: () => propDepth(node) },
      parentProperty: { get: () => nodeFacade(node.parent) },
      propertyIndex: { get: () => node.parent.children.indexOf(node) + 1 },
      propertyGroup: {
        value(n) {
          let x = node;
          for (let i = 0; i < (n === undefined ? 1 : n); i++) x = x.parent;
          return nodeFacade(x);
        },
      },
      enabled: { get: () => node.enabled !== false, set: (v) => { node.enabled = !!v; } },
    };
    const invalid = () => layer().removed;
    if (node.isGroup) {
      const def = Object.assign(common, childAccess(node), {
        propertyType: { get: () => (node.matchName === 'ADBE Effect Parade' ? E.PropertyType.INDEXED_GROUP : E.PropertyType.NAMED_GROUP) },
      });
      return makeObject(env, 'PropertyGroup ' + node.name, PropertyGroup.prototype, def, invalid);
    }
    const def = Object.assign(common, {
      propertyType: { value: E.PropertyType.PROPERTY },
      propertyValueType: { get: () => node.valueType },
      value: {
        get: () => {
          if (node.valueType === E.PropertyValueType.LAYER_INDEX) {
            const t = node.layerRef;
            return t && !t.removed ? layerIndex(t) : 0;
          }
          return node.value;
        },
      },
      expression: {
        get: () => node.expression,
        set: (v) => { if (!node.canSetExpression) throw new Error('cannot set expression'); node.expression = String(v); },
      },
      expressionEnabled: { get: () => node.expressionEnabled },
      canSetExpression: { get: () => node.canSetExpression },
      // probed by the script: a Property has no containingComp (reads undefined in AE)
      containingComp: { get: () => undefined },
      essentialPropertySource: {
        get: () => {
          if (version < 22) return undefined;
          return node.essentialSource ? node.essentialSource() : null;
        },
      },
    });
    return makeObject(env, 'Property ' + node.name, Property.prototype, def, invalid);
  }

  function itemFacade(it) {
    if (!it) return null;
    if (it.kind === 'comp') return compFacade(it);
    const main = it.main.solid
      ? makeObject(env, 'SolidSource', SolidSource.prototype, { isStill: { value: true } })
      : makeObject(env, 'FileSource', FileSource.prototype, { isStill: { value: !!it.main.still } });
    return makeObject(env, 'FootageItem', FootageItem.prototype, {
      id: { value: it.id }, name: { get: () => it.name }, mainSource: { value: main },
    }, () => it.removed);
  }

  function layerFacade(L) {
    const k = L.lkind;
    const isAV = !['camera', 'light'].includes(k);
    const proto = k === 'shape' ? ShapeLayer.prototype : k === 'text' ? TextLayer.prototype : k === 'camera'
      ? CameraLayer.prototype : k === 'light' ? LightLayer.prototype : AVLayer.prototype;
    const def = Object.assign({
      name: {
        get: () => L.name,
        set: (v) => {
          if (L.locked) throw new Error('Unable to rename a locked layer');
          renameLayer(L, String(v));
        },
      },
      index: { get: () => layerIndex(L) },
      containingComp: { get: () => compFacade(L.comp) },
      parent: { get: () => (L.parent && !L.parent.removed ? layerFacade(L.parent) : null) },
      locked: { get: () => L.locked, set: (v) => { L.locked = !!v; } },
      enabled: { get: () => L.enabled },
      solo: { get: () => L.solo },
      inPoint: { get: () => L.inPoint },
      outPoint: { get: () => L.outPoint },
      hasVideo: { get: () => L.hasVideo },
      nullLayer: { get: () => L.nullLayer },
      matchName: { get: () => L.matchName },
      propertyDepth: { value: 0 },
      propertyType: { value: E.PropertyType.INDEXED_GROUP },
      remove: {
        value() {
          if (L.locked) throw new Error('Unable to delete a locked layer');
          removeLayer(L);
        },
      },
    }, childAccess(L));
    if (isAV) {
      Object.assign(def, {
        hasAudio: { get: () => L.hasAudio },
        audioEnabled: { get: () => L.audioEnabled },
        adjustmentLayer: { get: () => L.adjustment },
        threeDLayer: { get: () => L.threeD },
        guideLayer: { get: () => L.guide },
        source: { get: () => itemFacade(L.source) },
        trackMatteType: { get: () => L.matteType },
        // AE 23.0+: the matte layer itself; older versions have no such attribute (reads undefined)
        trackMatteLayer: {
          get: () => {
            if (version < 23) return undefined;
            return L.matteLayer && !L.matteLayer.removed ? layerFacade(L.matteLayer) : null;
          },
        },
        essentialProperty: {
          get: () => {
            if (version < 22) return undefined;
            const g = essentialGroup(L);
            return g ? propFacade(g) : null;
          },
        },
      });
    }
    if (k === 'light') {
      def.lightSource = {
        get: () => {
          if (version < 24) return undefined;
          return L.lightSource && !L.lightSource.removed ? layerFacade(L.lightSource) : null;
        },
      };
    }
    return makeObject(env, `Layer ${L.name}`, proto, def, () => L.removed);
  }

  // essential properties of a precomp layer: one property per controller of the source comp
  function essentialGroup(L) {
    if (!L.source || L.source.kind !== 'comp') return null;
    if (!L.essential) {
      const g = { isGroup: true, name: 'Essential Properties', matchName: 'ADBE Layer Overrides', parent: L, children: [] };
      for (const c of L.source.egp) {
        g.children.push(prop(c.name, 'ADBE Layer Override', g, {
          essentialSource: () => {
            const src = c.layerNode;
            if (src.removed) return null;
            if (c.media) return layerFacade(src);
            return propFacade(findPath(src, c.prop));
          },
        }));
      }
      L.essential = g;
    }
    return L.essential;
  }

  function compFacade(c) {
    return makeObject(env, `Comp ${c.name}`, CompItem.prototype, {
      id: { value: c.id },
      name: { get: () => c.name },
      numLayers: { get: () => c.layers.length },
      layer: {
        value(i) {
          if (typeof i !== 'number' || i < 1 || i > c.layers.length || Math.floor(i) !== i) throw new Error(`layer(${i}) out of range`);
          return layerFacade(c.layers[i - 1]);
        },
      },
      layers: {
        value: {
          add(item) {
            const src = project.items.find((it) => it.id === item.id);
            if (!src) throw new Error('mock: unknown item');
            const L = buildLayer(c, { name: src.name, kind: src.kind === 'comp' ? 'precomp' : 'solid' });
            L.source = src;
            c.layers.unshift(L);
            env.counts.layersAdded++;
            return layerFacade(L);
          },
        },
      },
      selectedLayers: { get: () => env.varr(project.selection.filter((l) => l.comp === c && !l.removed).map(layerFacade)) },
      duration: { value: c.duration },
      width: { value: c.width },
      height: { value: c.height },
      pixelAspect: { value: c.pixelAspect },
      frameRate: { value: c.frameRate },
      usedIn: {
        get: () => env.varr(project.items.filter((it) => it.kind === 'comp' && it.layers.some((l) => l.source === c))
          .map(compFacade)),
      },
      motionGraphicsTemplateControllerCount: { get: () => (version < 16 ? undefined : c.egp.length) },
      remove: {
        value() {
          c.removed = true;
          project.items.splice(project.items.indexOf(c), 1);
          for (const l of c.layers) l.removed = true;
        },
      },
    }, () => c.removed);
  }

  // ----- mutations ------------------------------------------------------------
  function removeLayer(L) {
    const c = L.comp;
    const idx = c.layers.indexOf(L);
    if (idx < 0) throw new Error('mock: layer not in comp');
    c.layers.splice(idx, 1);
    L.removed = true;
    env.removed.push(`${c.name}/${L.name}`);
    for (const other of c.layers) {
      if (other.parent === L) other.parent = null; // AE un-parents the children
      if (other.matteLayer === L) {
        other.matteLayer = null;
        other.matteType = E.TrackMatteType.NO_TRACK_MATTE;
      }
      if (other.lightSource === L) other.lightSource = null;
      walkNodes(other, (n) => { if (n.layerRef === L) n.layerRef = null; });
    }
  }

  // AE updates expressions that use the old name (optional in the mock: config.autoUpdateExpressions)
  function renameLayer(L, newName) {
    const old = L.name;
    L.name = newName;
    env.renamed.push(`${old} -> ${newName}`);
    if (cfg.autoUpdateExpressions === false) return;
    const esc = old.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const re = new RegExp(`(\\blayer\\s*\\(\\s*)(["'])${esc}\\2`, 'g');
    for (const comp of project.items.filter((it) => it.kind === 'comp')) {
      for (const l of comp.layers) {
        walkNodes(l, (n) => {
          if (!n.expression) return;
          if (comp !== L.comp && n.expression.indexOf(`comp("${L.comp.name}")`) === -1) return;
          n.expression = n.expression.replace(re, (m, a, q) => a + q + newName + q);
        });
      }
    }
  }

  // ----- build project from spec ----------------------------------------------
  // comps are created in order, so precomps must come first
  for (const cs of cfg.comps || []) {
    const c = newComp(cs);
    project.items.push(c);
    for (const ls of cs.layers || []) {
      const L = buildLayer(c, ls);
      L.source = sourceFor(ls);
      c.layers.push(L);
    }
  }
  for (const c of project.items.filter((it) => it.kind === 'comp')) {
    for (const L of c.layers) {
      const s = L.spec;
      if (s.parent !== undefined) L.parent = resolveName(c, s.parent);
      if (s.matte) {
        L.matteType = E.TrackMatteType[s.matte.type || 'ALPHA'];
        // legacy (before 23.0): the matte is always the layer right above
        L.matteLayer = s.matte.layer !== undefined ? resolveName(c, s.matte.layer) : c.layers[c.layers.indexOf(L) - 1];
      }
      if (s.lightSource !== undefined) L.lightSource = resolveName(c, s.lightSource);
      walkNodes(L, (n) => { if (n.layerRefName !== undefined) n.layerRef = resolveName(c, n.layerRefName); });
    }
    for (const e of c.spec.egp || []) {
      c.egp.push({ name: e.name, prop: e.prop, media: !e.prop, layerNode: resolveName(c, e.layer) });
    }
  }
  const byName = (n) => project.items.find((it) => it.kind === 'comp' && it.name === n);
  if (cfg.active !== undefined) project.active = cfg.active === null ? null : byName(cfg.active);
  if (project.active) project.selection = (cfg.select || []).map((r) => resolveName(project.active, r));

  const app = makeObject(env, 'app', Object.prototype, {
    project: {
      value: makeObject(env, 'Project', Object.prototype, {
        activeItem: { get: () => (project.active ? compFacade(project.active) : (cfg.activeFootage ? itemFacade(newFootage('clip', { still: false })) : null)) },
        numItems: { get: () => project.items.length },
        item: {
          value(i) {
            if (i < 1 || i > project.items.length) throw new Error(`item(${i}) out of range`);
            return itemFacade(project.items[i - 1]);
          },
        },
        items: {
          value: {
            addComp(name, w, h, pa, dur, fps) {
              if (!(dur > 0) || !(fps > 0) || !(w > 0) || !(h > 0) || !(pa > 0)) throw new Error('addComp: bad arguments');
              const c = newComp({ name, duration: dur });
              project.items.push(c);
              env.counts.compsAdded++;
              return compFacade(c);
            },
          },
        },
      }),
    },
    beginUndoGroup: { value(name) { project.undo.push('begin:' + name); } },
    endUndoGroup: { value() { project.undo.push('end'); } },
  });

  // test helpers (not visible to the script)
  const inspect = {
    comp: byName,
    names: (compName) => byName(compName).layers.map((l) => l.name),
    layer: (compName, name) => byName(compName).layers.find((l) => l.name === name),
    items: () => project.items.map((it) => it.name),
    undo: project.undo,
    expression: (compName, layerName, path) => findPath(byName(compName).layers.find((l) => l.name === layerName), path).expression,
    select: (refs) => { project.selection = refs.map((r) => resolveName(project.active, r)); },
  };
  return { app, enums: E, classes, inspect };
}

// ---------------------------------------------------------------------------
// runner
// ---------------------------------------------------------------------------
function runScript(scriptPath, config) {
  const { ctx, varr } = createRealm();
  const env = { config, varr, errors: [], log: [], alerts: [], dialogs: [], removed: [], renamed: [],
    counts: { compsAdded: 0, layersAdded: 0 } };
  const sui = makeScriptUI(env);
  const ae = makeAE(env);
  const globals = Object.assign({
    app: ae.app,
    alert(msg, title) { env.alerts.push({ msg: String(msg), title }); },
    Panel: sui.Panel,
    Window: sui.Window,
    ScriptUI: sui.ScriptUI,
    $: { os: config.os === 'win' ? 'Windows/64 10.0' : 'Macintosh OS 14.0/64', global: vm.runInContext('this', ctx) },
  }, ae.enums, ae.classes);
  for (const [k, v] of Object.entries(globals)) ctx[k] = v;

  let source = fs.readFileSync(scriptPath, 'utf8');
  if (source.charCodeAt(0) === 0xfeff) source = source.slice(1);
  // run the file as a ScriptUI panel (this = Panel) or from File > Scripts (this = global)
  const host = config.asPalette ? undefined : sui.makePanel();
  ctx.__host__ = host;
  vm.runInContext(`(function () {\n${source}\n}).call(${host ? '__host__' : 'this'});`, ctx, { filename: scriptPath });
  const win = host || null;

  env.ae = ae.inspect;
  env.host = host;
  env.button = () => {
    const root = host;
    if (!root) throw new Error('no panel host');
    const btns = root._state.children.filter((c) => c._state.type === 'button');
    if (btns.length !== 1) throw new Error(`expected exactly one button, found ${btns.length}`);
    return btns[0];
  };
  // click 'Safe Delete' (opts.ctrl / opts.cmd / opts.shift hold the modifier keys)
  env.click = (opts) => {
    sui.keyboardState.ctrlKey = !!(opts && opts.ctrl);
    sui.keyboardState.metaKey = !!(opts && opts.cmd);
    sui.keyboardState.shiftKey = !!(opts && opts.shift);
    const before = env.dialogs.length;
    env.button().onClick();
    sui.keyboardState.ctrlKey = false;
    sui.keyboardState.metaKey = false;
    sui.keyboardState.shiftKey = false;
    return env.dialogs.length > before ? env.dialogs[env.dialogs.length - 1] : null;
  };
  env.win = win;
  return env;
}

module.exports = { runScript };
