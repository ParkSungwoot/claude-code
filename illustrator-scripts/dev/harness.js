'use strict';
/*
 * Mock ExtendScript runtime for Illustrator UI scripts:
 *  - an ES3-ish VM realm (ES5+ builtins removed so accidental use throws)
 *  - strict ScriptUI mock (unknown properties throw) with a scriptable "driver"
 *  - strict Illustrator DOM mock (documents, artboards, layers, page items, export APIs)
 *  - File/Folder mock backed by a sandbox directory on disk
 */
const vm = require('vm');
const fs = require('fs');
const path = require('path');
const os = require('os');

// ---------------------------------------------------------------------------
// ES3 realm
// ---------------------------------------------------------------------------
const STRIP = `
(function () {
  var i, list;
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
// strict proxy helper
// ---------------------------------------------------------------------------
const PASSTHROUGH = new Set(['toString', 'valueOf', 'constructor', 'toJSON', 'inspect', 'then', 'hasOwnProperty',
  'isPrototypeOf', 'propertyIsEnumerable', 'toLocaleString', '__proto__', 'toSource']);

function strict(target, allowed, label, errors) {
  return new Proxy(target, {
    get(t, prop, recv) {
      if (typeof prop === 'symbol' || PASSTHROUGH.has(prop)) return Reflect.get(t, prop, recv);
      if (!allowed.has(prop)) {
        const msg = `[${label}] read of unknown property '${String(prop)}'`;
        errors.push(msg);
        throw new Error(msg);
      }
      return Reflect.get(t, prop, recv);
    },
    set(t, prop, value, recv) {
      if (typeof prop !== 'symbol' && !allowed.has(prop)) {
        const msg = `[${label}] write of unknown property '${String(prop)}'`;
        errors.push(msg);
        throw new Error(msg);
      }
      return Reflect.set(t, prop, value, recv);
    },
    has(t, prop) {
      return allowed.has(prop) || Reflect.has(t, prop);
    },
  });
}

// ---------------------------------------------------------------------------
// ScriptUI mock
// ---------------------------------------------------------------------------
const COMMON_PROPS = ['type', 'text', 'enabled', 'visible', 'active', 'helpTip', 'alignment', 'preferredSize',
  'minimumSize', 'maximumSize', 'size', 'bounds', 'location', 'properties', 'parent', 'window', 'children',
  'justify', 'characters', 'onClick', 'onChange', 'onChanging', 'onActivate', 'onDeactivate', 'orientation',
  'alignChildren', 'spacing', 'margins', 'layout', 'add', 'remove', 'removeAll', 'items', 'selection', 'value',
  'minvalue', 'maxvalue', 'notify', 'indent', 'shortcutKey', 'addEventListener', 'removeEventListener',
  'textselection', 'title', 'itemSize', 'jumpdelta', 'stepdelta', 'graphics', 'onDraw', 'onShortcutKey', 'image',
  '_state'];
const WINDOW_PROPS = ['show', 'close', 'center', 'update', 'hide', 'onShow', 'onClose', 'onResize', 'onResizing',
  'onMove', 'onMoving', 'defaultElement', 'cancelElement', 'frameBounds', 'frameLocation', 'frameSize', 'opacity',
  'findElement', 'maximized', 'minimized', 'resizeable'];
const ITEM_PROPS = ['text', 'index', 'selected', 'checked', 'subItems', 'image', 'type', 'parent', 'expanded', 'toString'];
const CONTAINERS = new Set(['dialog', 'palette', 'window', 'panel', 'group', 'tabbedpanel', 'tab']);
const CONTROL_TYPES = new Set(['statictext', 'edittext', 'button', 'checkbox', 'radiobutton', 'dropdownlist', 'listbox',
  'slider', 'progressbar', 'panel', 'group', 'iconbutton', 'image', 'scrollbar', 'treeview', 'flashplayer',
  'tabbedpanel', 'tab']);

function makeDimension(errors, init) {
  const d = { width: init ? init[0] : 0, height: init ? init[1] : 0 };
  return strict(d, new Set(['width', 'height', '0', '1', 'length']), 'Dimension', errors);
}

class UI {
  constructor(env) {
    this.env = env;
    this.errors = env.errors;
    this.windows = [];
  }

  createControl(type, parent, text, creationProps, win, extra) {
    if (!CONTROL_TYPES.has(type) && !['dialog', 'palette', 'window'].includes(type)) {
      throw new Error(`ScriptUI mock: unknown control type '${type}'`);
    }
    const ui = this;
    const env = this.env;
    const allowed = new Set(COMMON_PROPS.concat(win ? WINDOW_PROPS : []));
    const state = {
      type,
      text: '',
      enabled: true,
      visible: true,
      active: false,
      helpTip: '',
      alignment: undefined,
      properties: creationProps || {},
      parent: parent || null,
      window: null,
      children: env.varr([]),
      justify: 'left',
      characters: undefined,
      orientation: undefined,
      alignChildren: undefined,
      spacing: undefined,
      margins: undefined,
      onClick: undefined,
      onChange: undefined,
      onChanging: undefined,
      value: undefined,
      minvalue: undefined,
      maxvalue: undefined,
      _items: [],
      _selection: null,
      _preferred: makeDimension(this.errors),
      _closed: false,
      _result: undefined,
    };
    if (type === 'dropdownlist' || type === 'listbox') {
      for (const t of Array.from(text || [])) state._items.push(ui.makeItem(String(t), state._items.length));
    } else if (type === 'slider') {
      // add('slider', bounds, value, min, max)
      state.value = Number(text) || 0;
      state.minvalue = Number(creationProps);
      state.maxvalue = Number(extra);
      state.properties = {};
      if (isNaN(state.minvalue) || isNaN(state.maxvalue)) throw new Error('slider needs min/max');
    } else if (type === 'progressbar') {
      // add('progressbar', bounds, value, max)
      state.value = Number(text) || 0;
      state.maxvalue = Number(creationProps);
      state.properties = {};
      if (isNaN(state.maxvalue)) throw new Error('progressbar needs max');
    } else if (typeof text === 'string') {
      state.text = text;
    } else if (text !== undefined) {
      throw new Error(`ScriptUI mock: non-string text for ${type}`);
    }
    if (type === 'checkbox' || type === 'radiobutton') state.value = false;

    const target = {};
    Object.defineProperties(target, {
      _state: { value: state, enumerable: false },
      preferredSize: {
        get: () => state._preferred,
        set: (v) => { state._preferred = toDimension(v, this.errors); },
        enumerable: true,
      },
      minimumSize: { get: () => makeDimension(this.errors), set: () => {}, enumerable: true },
      maximumSize: { get: () => makeDimension(this.errors), set: () => {}, enumerable: true },
      size: { get: () => state._preferred, set: (v) => { state._preferred = toDimension(v, this.errors); }, enumerable: true },
      items: { get: () => env.varr(state._items), enumerable: true },
      selection: {
        get: () => state._selection,
        set: (v) => {
          let item = null;
          if (v === null || v === undefined) item = null;
          else if (typeof v === 'number') {
            if (v < 0 || v >= state._items.length || Math.floor(v) !== v) throw new Error(`selection index out of range: ${v}`);
            item = state._items[v];
          } else if (state._items.includes(v)) item = v;
          else throw new Error('selection: unknown item');
          const changed = item !== state._selection;
          state._selection = item;
          // Real ScriptUI fires onChange for programmatic selection changes on dropdowns.
          if (changed && type === 'dropdownlist' && typeof proxy.onChange === 'function') {
            ui.env.log.push(`onChange fired by programmatic selection on dropdown`);
            proxy.onChange();
          }
        },
        enumerable: true,
      },
      layout: { get: () => ({ layout() {}, resize() {} }), enumerable: true },
      graphics: {
        get: () => { throw new Error('graphics not supported by mock (avoid for portability)'); },
        enumerable: true,
      },
    });
    for (const k of ['type', 'text', 'enabled', 'visible', 'active', 'helpTip', 'alignment', 'properties', 'parent',
      'window', 'children', 'justify', 'characters', 'orientation', 'alignChildren', 'spacing', 'margins', 'onClick',
      'onChange', 'onChanging', 'value', 'minvalue', 'maxvalue', 'indent', 'shortcutKey', 'textselection', 'title',
      'onDraw', 'onShortcutKey', 'image', 'itemSize', 'jumpdelta', 'stepdelta', 'onActivate', 'onDeactivate',
      'location', 'bounds']) {
      Object.defineProperty(target, k, {
        get: () => state[k],
        set: (v) => {
          if (k === 'text' && typeof v !== 'string') throw new Error(`text must be a string (got ${typeof v})`);
          if (k === 'value' && (type === 'checkbox' || type === 'radiobutton') && typeof v !== 'boolean') {
            throw new Error(`${type}.value must be boolean`);
          }
          if (k === 'alignment' || k === 'alignChildren') checkAlignment(v, k);
          if (k === 'orientation' && !['row', 'column', 'stack'].includes(v)) throw new Error(`bad orientation ${v}`);
          state[k] = v;
        },
        enumerable: true,
      });
    }
    target.add = function (childType, bounds, childText, props, extra) {
      if (childType === 'item') {
        // ListBox/DropDownList: add('item', text [, index])
        if (type !== 'dropdownlist' && type !== 'listbox') throw new Error(`add('item') on ${type}`);
        if (typeof bounds !== 'string') throw new Error('item text must be string, got ' + typeof bounds);
        if (childText !== undefined) throw new Error('mock: insertion index not supported');
        const it = ui.makeItem(bounds, state._items.length);
        state._items.push(it);
        return it;
      }
      if (!CONTAINERS.has(type)) throw new Error(`add() called on non-container ${type}`);
      if (bounds !== undefined) throw new Error('mock expects bounds undefined');
      const child = ui.createControl(childType, proxy, childText, props, false, extra);
      child._state.window = state.window || proxy;
      state.children.push(child);
      return child;
    };
    target.remove = function () { throw new Error('remove not supported in mock'); };
    target.removeAll = function () {
      if (type !== 'dropdownlist' && type !== 'listbox') throw new Error(`removeAll on ${type}`);
      state._items = [];
      state._selection = null;
    };
    target.notify = function (ev) {
      const h = proxy[ev || 'onClick'];
      if (typeof h === 'function') h.call(proxy);
    };
    target.addEventListener = function () {};
    target.removeEventListener = function () {};
    if (win) {
      target.show = function () { return ui.showWindow(proxy); };
      target.close = function (result) {
        state._closed = true;
        state._result = result === undefined ? 0 : result;
        if (typeof proxy.onClose === 'function') proxy.onClose();
      };
      target.center = function () {};
      target.update = function () { env.counts.windowUpdate++; };
      target.hide = function () { state._closed = true; };
      for (const k of ['onShow', 'onClose', 'onResize', 'onResizing', 'onMove', 'onMoving', 'defaultElement',
        'cancelElement', 'opacity', 'frameBounds', 'frameLocation', 'frameSize', 'maximized', 'minimized', 'resizeable']) {
        Object.defineProperty(target, k, { get: () => state[k], set: (v) => { state[k] = v; }, enumerable: true });
      }
      target.findElement = function (name) { return ui.findByName(proxy, name); };
    }

    const proxy = strict(target, allowed, `ScriptUI ${type}`, this.errors);
    if (win) state.window = proxy;
    return proxy;
  }

  makeItem(text, index) {
    const it = { text, index, selected: false, checked: false, subItems: this.env.varr([]), image: null, type: 'item',
      parent: null, expanded: false };
    it.toString = function () { return this.text; };
    return strict(it, new Set(ITEM_PROPS), 'ListItem', this.errors);
  }

  showWindow(win) {
    const st = win._state;
    if (st.type === 'palette' || st.type === 'window') {
      this.env.log.push(`palette shown: ${st.text}`);
      return undefined;
    }
    this.env.counts.dialogsShown++;
    if (typeof win.onShow === 'function') win.onShow();
    const driver = this.env.config.driver;
    if (!driver) throw new Error('No UI driver for dialog ' + st.text);
    driver(new Driver(win, this.env), win);
    if (!st._closed) {
      // user pressed the window close box
      st._closed = true;
      st._result = 2;
      if (typeof win.onClose === 'function') win.onClose();
    }
    return st._result;
  }

  findByName(root, name) {
    let found = null;
    walk(root, (c) => { if (!found && c._state.properties && c._state.properties.name === name) found = c; });
    return found;
  }
}

function toDimension(v, errors) {
  if (Array.isArray(v) || (v && typeof v.length === 'number')) return makeDimension(errors, [v[0], v[1]]);
  if (v && typeof v === 'object') return makeDimension(errors, [v.width, v.height]);
  throw new Error('bad dimension value');
}

const ALIGN_VALUES = new Set(['left', 'right', 'center', 'fill', 'top', 'bottom']);
function checkAlignment(v, key) {
  const list = typeof v === 'string' ? [v] : Array.from(v);
  if (list.length < 1 || list.length > 2) throw new Error(`bad ${key}: ${v}`);
  for (const x of list) if (!ALIGN_VALUES.has(x)) throw new Error(`bad ${key} value: ${x}`);
}

function walk(ctrl, fn) {
  fn(ctrl);
  for (const c of Array.from(ctrl._state.children)) walk(c, fn);
}

// Driver = what a test uses to "click" around in a dialog
class Driver {
  constructor(win, env) {
    this.win = win;
    this.env = env;
  }

  all(type) {
    const out = [];
    walk(this.win, (c) => { if (!type || c._state.type === type) out.push(c); });
    return out;
  }

  find(type, text) {
    const matches = this.all(type).filter((c) => matchText(c._state.text, text));
    if (matches.length !== 1) {
      throw new Error(`find(${type}, ${text}) matched ${matches.length}: ` +
        this.all(type).map((c) => JSON.stringify(c._state.text)).join(', '));
    }
    return matches[0];
  }

  // The control of the given type that follows a statictext label in the same row.
  after(labelText, type) {
    const labels = this.all().filter((c) => ['statictext', 'radiobutton', 'checkbox'].includes(c._state.type) &&
      matchText(c._state.text, labelText));
    if (labels.length !== 1) throw new Error(`after(${labelText}) matched ${labels.length} labels`);
    const label = labels[0];
    const siblings = Array.from(label._state.parent._state.children);
    const idx = siblings.indexOf(label);
    for (let i = idx + 1; i < siblings.length; i++) {
      if (!type || siblings[i]._state.type === type) return siblings[i];
    }
    throw new Error(`no ${type} after label ${labelText}`);
  }

  ensureUsable(c) {
    if (this.win._state._closed) throw new Error('interaction after dialog closed');
    let p = c;
    while (p) {
      if (!p._state.enabled) throw new Error(`control disabled: ${p._state.type} ${p._state.text}`);
      if (!p._state.visible) throw new Error(`control hidden: ${p._state.type} ${p._state.text}`);
      p = p._state.parent;
    }
  }

  isUsable(c) {
    try { this.ensureUsable(c); return true; } catch (e) { return false; }
  }

  click(c) {
    this.ensureUsable(c);
    const st = c._state;
    if (st.type === 'checkbox') st.value = !st.value;
    if (st.type === 'radiobutton') {
      // radio buttons that are consecutive siblings form one group
      const siblings = Array.from(st.parent._state.children);
      const idx = siblings.indexOf(c);
      for (let i = idx - 1; i >= 0 && siblings[i]._state.type === 'radiobutton'; i--) siblings[i]._state.value = false;
      for (let i = idx + 1; i < siblings.length && siblings[i]._state.type === 'radiobutton'; i++) siblings[i]._state.value = false;
      st.value = true;
    }
    if (typeof c.onClick === 'function') c.onClick.call(c);
    else if (st.type === 'button' && st.properties && st.properties.name === 'ok') this.win.close(1);
    else if (st.type === 'button' && st.properties && st.properties.name === 'cancel') this.win.close(2);
  }

  type(c, text) {
    this.ensureUsable(c);
    if (c._state.type !== 'edittext') throw new Error('type() on ' + c._state.type);
    c._state.text = text;
    if (typeof c.onChanging === 'function') c.onChanging.call(c);
    if (typeof c.onChange === 'function') c.onChange.call(c);
  }

  select(c, index) {
    this.ensureUsable(c);
    c.selection = index; // setter fires onChange
  }

  slide(c, value) {
    this.ensureUsable(c);
    c._state.value = value;
    if (typeof c.onChanging === 'function') c.onChanging.call(c);
    if (typeof c.onChange === 'function') c.onChange.call(c);
  }

  button(text) { return this.find('button', text); }
  ok(text) { this.click(this.button(text)); }
  cancel() { this.click(this.button('취소')); }
  texts() { return this.all('statictext').map((c) => c._state.text); }
  listItems(lb) { return lb._state._items.map((i) => i.text); }
}

function matchText(actual, expected) {
  if (expected instanceof RegExp) return expected.test(actual);
  return actual === expected;
}

// ---------------------------------------------------------------------------
// File / Folder mock
// ---------------------------------------------------------------------------
function makeFileSystem(env) {
  const root = env.root;
  const home = path.join(root, 'home');
  const special = {
    userData: path.join(root, 'userData'),
    temp: path.join(root, 'temp'),
    desktop: path.join(home, 'Desktop'),
    myDocuments: path.join(home, 'Documents'),
  };
  for (const p of Object.values(special)) fs.mkdirSync(p, { recursive: true });

  const encodeSegment = (s) => encodeURIComponent(s).replace(/%2F/gi, '/');
  const toURI = (abs) => abs.split('/').map((s) => (s ? encodeSegment(s) : s)).join('/');

  function resolveInput(p) {
    if (typeof p !== 'string') throw new Error('File/Folder path must be a string, got ' + typeof p);
    if (/\\/.test(p)) throw new Error('mock: backslash path ' + p);
    let s = p;
    let decoded;
    try { decoded = decodeURIComponent(s); } catch (e) { decoded = s; }
    s = decoded;
    if (s === '~' || s.startsWith('~/')) s = home + s.slice(1);
    if (!s.startsWith('/')) s = path.join(root, 'cwd', s);
    return path.normalize(s);
  }

  const FILE_PROPS = new Set(['name', 'displayName', 'fullName', 'fsName', 'absoluteURI', 'path', 'parent', 'exists',
    'encoding', 'lineFeed', 'error', 'length', 'created', 'modified', 'hidden', 'readonly', 'alias', 'type', 'creator',
    'eof', 'open', 'close', 'read', 'readln', 'write', 'writeln', 'copy', 'remove', 'rename', 'execute', 'getFiles',
    'create', 'selectDlg', 'changePath', 'resolve', 'getRelativeURI', 'relativeURI', 'seek', 'tell', 'openDlg', 'saveDlg',
    '_abs', '_isFolder']);

  function makeEntry(abs, isFolder) {
    const target = {
      _abs: abs,
      _isFolder: isFolder,
      encoding: 'ASCII',
      lineFeed: 'Unix',
      error: '',
      _fd: null,
      _mode: null,
      _buffer: '',
    };
    Object.defineProperties(target, {
      name: { get: () => encodeSegment(path.basename(abs)), enumerable: true },
      displayName: { get: () => path.basename(abs), enumerable: true },
      fullName: { get: () => toURI(abs), enumerable: true },
      absoluteURI: { get: () => toURI(abs), enumerable: true },
      fsName: { get: () => abs, enumerable: true },
      path: { get: () => toURI(path.dirname(abs)), enumerable: true },
      parent: { get: () => FolderCtor(path.dirname(abs)), enumerable: true },
      exists: {
        get: () => {
          // macOS / Windows file systems are case-insensitive by default
          let real = abs;
          if (!fs.existsSync(real)) {
            const dir = path.dirname(abs);
            if (!fs.existsSync(dir)) return false;
            const hit = fs.readdirSync(dir).find((n) => n.toLowerCase() === path.basename(abs).toLowerCase());
            if (!hit) return false;
            real = path.join(dir, hit);
          }
          const isDir = fs.statSync(real).isDirectory();
          return isFolder ? isDir : true;
        },
        enumerable: true,
      },
    });
    target.toString = () => toURI(abs);
    target.remove = () => {
      if (!fs.existsSync(abs)) return false;
      if (fs.statSync(abs).isDirectory()) {
        if (fs.readdirSync(abs).length) return false;
        fs.rmdirSync(abs);
      } else fs.unlinkSync(abs);
      return true;
    };
    target.execute = () => { env.executed.push(abs); return true; };
    if (isFolder) {
      target.create = () => { fs.mkdirSync(abs, { recursive: true }); return true; };
      target.getFiles = (mask) => {
        if (mask !== undefined) throw new Error('mock getFiles mask unsupported');
        if (!fs.existsSync(abs)) return env.varr([]);
        return env.varr(fs.readdirSync(abs).sort().map((n) => {
          const p = path.join(abs, n);
          return fs.statSync(p).isDirectory() ? FolderCtor(p) : FileCtor(p);
        }));
      };
      target.selectDlg = (prompt) => {
        env.dialogs.push({ kind: 'selectDlg', prompt, start: abs });
        const pick = env.config.pickFolder;
        return pick ? FolderCtor(pick) : null;
      };
    } else {
      target.open = (mode) => {
        target._mode = mode;
        if (mode === 'r') {
          if (!fs.existsSync(abs)) return false;
          target._buffer = fs.readFileSync(abs, target.encoding === 'UTF-8' ? 'utf8' : 'latin1');
          if (target.encoding === 'UTF-8' && target._buffer.charCodeAt(0) === 0xfeff) target._buffer = target._buffer.slice(1);
        } else if (mode === 'w') {
          target._buffer = '';
        } else throw new Error('mock open mode ' + mode);
        return true;
      };
      target.read = () => { if (target._mode !== 'r') throw new Error('read without open r'); return target._buffer; };
      target.write = (s) => { if (target._mode !== 'w') throw new Error('write without open w'); target._buffer += String(s); return true; };
      target.close = () => {
        if (target._mode === 'w') {
          if (target.encoding !== 'UTF-8' && /[^\x00-\x7f]/.test(target._buffer)) {
            throw new Error('writing non-ASCII without UTF-8 encoding');
          }
          fs.writeFileSync(abs, target._buffer, 'utf8');
        }
        target._mode = null;
        return true;
      };
      target.copy = (dest) => {
        const destAbs = resolveInput(String(dest));
        if (!fs.existsSync(abs)) return false;
        if (!fs.existsSync(path.dirname(destAbs))) return false;
        fs.copyFileSync(abs, destAbs);
        return true;
      };
    }
    return strict(target, FILE_PROPS, isFolder ? 'Folder' : 'File', env.errors);
  }

  function FileCtor(p) {
    return makeEntry(resolveInput(p), false);
  }
  function FolderCtor(p) {
    return makeEntry(resolveInput(p), true);
  }

  // `x instanceof Folder` support
  const FileClass = function (p) { return FileCtor(p); };
  const FolderClass = function (p) { return FolderCtor(p); };
  Object.defineProperty(FolderClass, Symbol.hasInstance, { value: (x) => !!(x && x._isFolder === true) });
  Object.defineProperty(FileClass, Symbol.hasInstance, { value: (x) => !!(x && x._isFolder === false) });
  FileClass.fs = env.config.os === 'win' ? 'Windows' : 'Macintosh';
  FileClass.encode = (s) => encodeURIComponent(s).replace(/%2F/gi, '/');
  FileClass.decode = (s) => decodeURIComponent(s);
  Object.defineProperty(FolderClass, 'userData', { get: () => FolderCtor(special.userData) });
  Object.defineProperty(FolderClass, 'temp', { get: () => FolderCtor(special.temp) });
  Object.defineProperty(FolderClass, 'desktop', { get: () => FolderCtor(special.desktop) });
  Object.defineProperty(FolderClass, 'myDocuments', { get: () => FolderCtor(special.myDocuments) });
  FolderClass.selectDialog = (prompt) => {
    env.dialogs.push({ kind: 'selectDialog', prompt });
    return env.config.pickFolder ? FolderCtor(env.config.pickFolder) : null;
  };
  return { File: FileClass, Folder: FolderClass, special, home };
}

// ---------------------------------------------------------------------------
// Illustrator DOM mock
// ---------------------------------------------------------------------------
function enumOf(name, members, errors) {
  return strict(Object.assign({}, members), new Set(Object.keys(members)), `enum ${name}`, errors);
}

const OPTION_CLASSES = {
  ExportOptionsPNG24: ['antiAliasing', 'artBoardClipping', 'dimensions', 'horizontalScale', 'matte', 'matteColor',
    'saveAsHTML', 'transparency', 'verticalScale'],
  ExportOptionsJPEG: ['antiAliasing', 'artBoardClipping', 'blurAmount', 'horizontalScale', 'matte', 'matteColor',
    'optimization', 'qualitySetting', 'saveAsHTML', 'verticalScale'],
  ExportOptionsWebOptimizedSVG: ['artboardRange', 'coordinatePrecision', 'cssProperties', 'fontType',
    'rasterImageLocation', 'saveMultipleArtboards', 'svgId', 'svgMinify', 'svgResponsive'],
  ExportForScreensItemToExport: ['artboards', 'document', 'assets'],
  ExportForScreensPDFOptions: ['pdfPreset'],
};

function makeIllustrator(env, fsys) {
  const errors = env.errors;
  const E = {
    ExportType: enumOf('ExportType', { AUTOCAD: 8, FLASH: 7, GIF: 6, JPEG: 1, PHOTOSHOP: 2, PNG24: 5, PNG8: 4, SVG: 3, TIFF: 9, WOSVG: 10 }, errors),
    SVGFontType: enumOf('SVGFontType', { OUTLINEFONT: 3, SVGFONT: 2, CEFFONT: 1 }, errors),
    RasterImageLocation: enumOf('RasterImageLocation', { EMBED: 0, LINK: 1, PRESERVE: 2 }, errors),
    RulerUnits: enumOf('RulerUnits', { Centimeters: 3, Inches: 2, Millimeters: 6, Picas: 5, Pixels: 8, Points: 4, Qs: 7, Unknown: 1 }, errors),
    UserInteractionLevel: enumOf('UserInteractionLevel', { DISPLAYALERTS: 2, DONTDISPLAYALERTS: -1 }, errors),
    SaveOptions: enumOf('SaveOptions', { DONOTSAVECHANGES: 2, PROMPTTOSAVECHANGES: 3, SAVECHANGES: 1 }, errors),
    ExportForScreensType: enumOf('ExportForScreensType', { SE_PDF: 1, SE_PNG8: 2, SE_PNG24: 3, SE_JPEG100: 4, SE_JPEG80: 5, SE_JPEG60: 6, SE_JPEG30: 7, SE_SVG: 8 }, errors),
  };
  const classes = {};
  for (const [name, props] of Object.entries(OPTION_CLASSES)) {
    classes[name] = function () {
      const t = { _class: name };
      return strict(t, new Set(props.concat(['_class'])), name, errors);
    };
  }

  const documents = [];
  let active = null;
  const app = {
    get documents() { return env.varr(documents); },
    get activeDocument() {
      if (!active) throw new Error('There is no document');
      return active;
    },
    set activeDocument(d) {
      if (!documents.includes(d)) throw new Error('not a document');
      active = d;
      env.log.push('activate ' + d.name);
    },
    version: env.config.version || '28.0.0',
    userInteractionLevel: E.UserInteractionLevel.DISPLAYALERTS,
    redraw() { env.counts.redraw++; },
    undo() { throw new Error('app.undo() must not be used'); },
    get PDFPresetsList() {
      if (env.config.pdfPresetsThrows) throw new Error('presets unavailable');
      return env.varr(env.config.pdfPresets || ['[Illustrator Default]', '[High Quality Print]', '[Smallest File Size]']);
    },
    preferences: strict({
      getBooleanPreference(key) {
        const prefs = env.config.prefs || { includeStrokeInBounds: true, transformPatterns: false };
        if (!(key in prefs)) throw new Error('unknown preference ' + key);
        return prefs[key];
      },
    }, new Set(['getBooleanPreference']), 'Preferences', errors),
  };
  const appProxy = strict(app, new Set(['documents', 'activeDocument', 'version', 'userInteractionLevel', 'redraw',
    'undo', 'PDFPresetsList', 'preferences']), 'Application', errors);

  function addDocument(spec) {
    const doc = makeDocument(spec);
    documents.push(doc);
    if (!active || spec.active) active = doc;
    return doc;
  }

  function makeDocument(spec) {
    const artboards = (spec.artboards || [{ name: 'Artboard 1', rect: [0, 0, 100, -100] }]).map((a) => makeArtboard(a));
    let activeArtboard = spec.activeArtboard || 0;
    const artboardsArr = env.varr(artboards);
    artboardsArr.getActiveArtboardIndex = () => activeArtboard;
    artboardsArr.setActiveArtboardIndex = (i) => {
      if (typeof i !== 'number' || i < 0 || i >= artboards.length) throw new Error('bad artboard index ' + i);
      activeArtboard = i;
    };
    const layers = makeLayers(spec.layers || [{ name: 'Layer 1' }]);
    const items = (spec.selection || []).map((s) => makeItem(s));
    const fileAbs = spec.file ? path.join(env.root, spec.file) : null;
    if (fileAbs) {
      fs.mkdirSync(path.dirname(fileAbs), { recursive: true });
      fs.writeFileSync(fileAbs, 'ai');
    }
    const d = {
      name: spec.name || (fileAbs ? path.basename(fileAbs) : 'Untitled-1'),
      get fullName() {
        if (!fileAbs) {
          if (env.config.unsavedFullNameThrows) throw new Error('no file');
          return fsys.File(spec.name || 'Untitled-1');
        }
        return fsys.File(fileAbs);
      },
      get path() { return fileAbs ? fsys.Folder(path.dirname(fileAbs)) : fsys.Folder(''); },
      saved: true,
      rulerUnits: spec.rulerUnits !== undefined ? spec.rulerUnits : E.RulerUnits.Millimeters,
      artboards: artboardsArr,
      layers,
      get selection() {
        if (spec.textEditing) return strict({ typename: 'TextRange', length: 5, contents: 'hello' }, new Set(['typename', 'length', 'contents']), 'TextRange', errors);
        return env.varr(items);
      },
      activeLayer: layers[0],
      _items: items,
      _artboards: artboards,
      _layers: layers,
      _exports: [],
      get _activeArtboard() { return activeArtboard; },
      activate() { appProxy.activeDocument = proxy; },
      exportFile(file, type, options) {
        if (!file || file._isFolder !== false) throw new Error('exportFile: file must be a File');
        const typeName = Object.keys(E.ExportType).find((k) => E.ExportType[k] === type);
        if (!typeName) throw new Error('exportFile: bad type');
        const expected = { PNG24: 'ExportOptionsPNG24', JPEG: 'ExportOptionsJPEG', WOSVG: 'ExportOptionsWebOptimizedSVG' }[typeName];
        if (!expected) throw new Error('exportFile: unexpected type ' + typeName);
        if (!options || options._class !== expected) throw new Error(`exportFile: options must be ${expected}`);
        const o = Object.assign({}, options);
        if (typeName !== 'WOSVG') {
          for (const k of ['horizontalScale', 'verticalScale']) {
            if (o[k] !== undefined && (o[k] <= 0 || o[k] > 776.19)) throw new Error(`exportFile: ${k} out of range: ${o[k]}`);
          }
          if (o.qualitySetting !== undefined && (o.qualitySetting < 0 || o.qualitySetting > 100 || Math.round(o.qualitySetting) !== o.qualitySetting)) {
            throw new Error('exportFile: bad qualitySetting');
          }
        }
        const record = { method: 'exportFile', doc: proxy.name, type: typeName, activeArtboard, options: o };
        let outPath = file.fsName;
        if (typeName === 'WOSVG' && o.saveMultipleArtboards) {
          const idx = parseInt(o.artboardRange, 10) - 1;
          if (!(idx >= 0 && idx < artboards.length) || String(idx + 1) !== o.artboardRange) throw new Error('bad artboardRange ' + o.artboardRange);
          record.artboard = idx;
          outPath = path.join(path.dirname(outPath), path.basename(outPath, '.svg') + '_' + artboards[idx].name + '.svg');
        } else {
          record.artboard = activeArtboard;
        }
        if (env.config.failExportFor && env.config.failExportFor(record)) throw new Error('simulated export failure');
        fs.writeFileSync(outPath, JSON.stringify(record));
        proxy._exports.push(record);
      },
      exportForScreens(folder, type, options, item, prefix) {
        if (!folder || folder._isFolder !== true) throw new Error('exportForScreens: folder must be a Folder');
        const typeName = Object.keys(E.ExportForScreensType).find((k) => E.ExportForScreensType[k] === type);
        if (typeName !== 'SE_PDF') throw new Error('exportForScreens: unexpected type ' + typeName);
        if (!options || options._class !== 'ExportForScreensPDFOptions') throw new Error('exportForScreens: bad options');
        if (!item || item._class !== 'ExportForScreensItemToExport') throw new Error('exportForScreens: bad item');
        if (typeof prefix !== 'string') throw new Error('exportForScreens: prefix must be string');
        if (item.document !== false) throw new Error('exportForScreens: expected document=false');
        const idx = parseInt(item.artboards, 10) - 1;
        if (!(idx >= 0 && idx < artboards.length) || String(idx + 1) !== item.artboards) throw new Error('bad artboards ' + item.artboards);
        const record = { method: 'exportForScreens', doc: proxy.name, type: typeName, artboard: idx, options: Object.assign({}, options), prefix };
        const sub = path.join(folder.fsName, 'PDF');
        fs.mkdirSync(sub, { recursive: true });
        fs.writeFileSync(path.join(sub, prefix + artboards[idx].name + '.pdf'), JSON.stringify(record));
        proxy._exports.push(record);
      },
    };
    const proxy = strict(d, new Set(['name', 'fullName', 'path', 'saved', 'rulerUnits', 'artboards', 'layers', 'selection',
      'activeLayer', 'activate', 'exportFile', 'exportForScreens', '_items', '_artboards', '_layers', '_exports',
      '_activeArtboard']), 'Document', errors);
    return proxy;
  }

  function makeArtboard(a) {
    const t = {
      name: a.name,
      get artboardRect() { return env.varr(a.rect); },
      set artboardRect(v) { a.rect = Array.from(v); },
    };
    Object.defineProperty(t, 'name', {
      get: () => a.name,
      set: (v) => {
        if (typeof v !== 'string') throw new Error('artboard name must be string');
        if (v === '') throw new Error('empty artboard name');
        a.name = v;
      },
      enumerable: true,
    });
    return strict(t, new Set(['name', 'artboardRect', 'rulerOrigin', 'rulerPAR', 'showCenter', 'showCrossHairs', 'showSafeAreas']), 'Artboard', errors);
  }

  function makeLayers(specs) {
    return env.varr(specs.map((s) => {
      const t = { typename: 'Layer', locked: !!s.locked, visible: s.visible !== false, _spec: s };
      Object.defineProperty(t, 'name', {
        get: () => s.name,
        set: (v) => {
          if (typeof v !== 'string') throw new Error('layer name must be string');
          if (s.lockedName) throw new Error('Target layer cannot be modified');
          s.name = v;
        },
        enumerable: true,
      });
      t.layers = makeLayers(s.layers || []);
      return strict(t, new Set(['typename', 'name', 'layers', 'locked', 'visible', '_spec']), 'Layer', errors);
    }));
  }

  const ITEM_COMMON = ['typename', 'name', 'geometricBounds', 'visibleBounds', 'translate', 'locked', 'hidden', 'parent',
    'layer', 'left', 'top', 'width', 'height', 'position', 'uuid', '_spec'];
  const ITEM_EXTRA = {
    TextFrame: ['contents', 'textRange', 'kind'],
    GroupItem: ['clipped', 'pageItems', 'pathItems', 'compoundPathItems'],
    PathItem: ['clipping', 'filled', 'stroked', 'strokeWidth'],
    CompoundPathItem: ['pathItems'],
  };

  function makeItem(s) {
    s.bounds = s.bounds.slice();
    const stroke = s.stroke || 0;
    const t = {
      typename: s.type,
      get geometricBounds() { return env.varr(s.bounds); },
      get visibleBounds() {
        const b = s.bounds;
        return env.varr([b[0] - stroke / 2, b[1] + stroke / 2, b[2] + stroke / 2, b[3] - stroke / 2]);
      },
      translate(dx, dy, objects, fillPatterns, fillGradients, strokePattern) {
        if (arguments.length !== 6) throw new Error('translate expects 6 args in these scripts');
        if (typeof dx !== 'number' || typeof dy !== 'number' || !isFinite(dx) || !isFinite(dy)) throw new Error('translate: bad delta');
        for (const b of [objects, fillPatterns, fillGradients, strokePattern]) if (typeof b !== 'boolean') throw new Error('translate: flags must be boolean');
        if (s.locked) throw new Error('Target layer cannot be modified');
        env.translateCalls.push({ name: s.name, dx, dy, flags: [objects, fillPatterns, fillGradients, strokePattern] });
        s.bounds = [s.bounds[0] + dx, s.bounds[1] + dy, s.bounds[2] + dx, s.bounds[3] + dy];
        if (s.children) for (const c of s.children) c._shift(dx, dy);
      },
      locked: !!s.locked,
      hidden: false,
      _spec: s,
    };
    Object.defineProperty(t, 'name', {
      get: () => s.name || '',
      set: (v) => { if (typeof v !== 'string') throw new Error('name must be string'); s.name = v; },
      enumerable: true,
    });
    if (s.type === 'TextFrame') {
      Object.defineProperty(t, 'contents', {
        get: () => s.contents,
        set: (v) => { if (typeof v !== 'string') throw new Error('contents must be string'); s.contents = v; },
        enumerable: true,
      });
    }
    if (s.type === 'GroupItem') {
      t.clipped = !!s.clipped;
      const kids = (s.children || []).map((c) => makeChild(c));
      t.pageItems = env.varr(kids);
    }
    if (s.type === 'PathItem') t.clipping = !!s.clipping;
    if (s.type === 'CompoundPathItem') t.pathItems = env.varr((s.paths || []).map((c) => makeItem(c)));
    const allowed = new Set(ITEM_COMMON.concat(ITEM_EXTRA[s.type] || []));
    return strict(t, allowed, s.type, errors);
  }

  function makeChild(c) {
    const p = makeItem(c);
    c._shift = (dx, dy) => { c.bounds = [c.bounds[0] + dx, c.bounds[1] + dy, c.bounds[2] + dx, c.bounds[3] + dy]; };
    return p;
  }

  return { app: appProxy, enums: E, classes, addDocument, documents };
}

// ---------------------------------------------------------------------------
// runner
// ---------------------------------------------------------------------------
function runScript(scriptPath, config) {
  const root = config.root || fs.mkdtempSync(path.join(config.tmpBase || os.tmpdir(), 'ai-mock-'));
  const { ctx, varr } = createRealm();
  const env = {
    root, config, varr, errors: [], log: [], alerts: [], dialogs: [], executed: [], translateCalls: [],
    counts: { redraw: 0, dialogsShown: 0, windowUpdate: 0 },
  };
  if (config.setup) config.setup(env);
  const fsys = makeFileSystem(env);
  const ui = new UI(env);
  const ai = makeIllustrator(env, fsys);
  for (const spec of config.documents || []) ai.addDocument(spec);

  const globals = {
    app: ai.app,
    File: fsys.File,
    Folder: fsys.Folder,
    alert(msg, title, errorIcon) {
      env.alerts.push({ msg: String(msg), title, errorIcon: !!errorIcon });
    },
    confirm(msg) { env.alerts.push({ msg: String(msg), confirm: true }); return !!config.confirmResult; },
    Window: function (type, title, bounds, props) {
      if (!['dialog', 'palette', 'window'].includes(type)) throw new Error('bad window type ' + type);
      if (bounds !== undefined) throw new Error('mock expects window bounds undefined');
      const w = ui.createControl(type, null, title, props, true);
      ui.windows.push(w);
      return w;
    },
    $: { os: config.os === 'win' ? 'Windows/64 10.0' : 'Macintosh OS 14.0/64', writeln() {}, global: null },
  };
  Object.assign(globals, ai.enums, ai.classes);
  for (const [k, v] of Object.entries(globals)) ctx[k] = v;

  let source = fs.readFileSync(scriptPath, 'utf8');
  if (source.charCodeAt(0) === 0xfeff) source = source.slice(1);
  let thrown = null;
  try {
    vm.runInContext(source, ctx, { filename: scriptPath });
  } catch (e) {
    thrown = e;
  }
  env.fsys = fsys;
  env.ai = ai;
  env.ui = ui;
  env.thrown = thrown;
  return env;
}

module.exports = { runScript, Driver };
