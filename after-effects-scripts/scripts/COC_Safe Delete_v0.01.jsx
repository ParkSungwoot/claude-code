/*
 * ============================================================================
 *  COC Safe Delete  (COC_Safe Delete_v0.01.jsx)  v0.01
 * ============================================================================
 *  선택한 레이어를 지워도 컴포지션에 영향이 없는지 먼저 검사하고,
 *  영향이 없는 레이어만 삭제합니다. 지우면 안 되는 레이어는 이유를 알려 주고 남겨 둡니다.
 *
 *  레이어를 선택하고 클릭          선택한 레이어만 검사해서, 안전한 것만 삭제
 *  아무것도 선택하지 않고 클릭     지금 컴포지션의 모든 레이어를 정리
 *  아무것도 선택하지 않고 Shift+클릭  안에 든 프리컴프까지 끝까지 모두 정리
 *  Ctrl(Mac: Cmd)을 함께 누르면    위와 같이 정리한 뒤, 남긴 레이어 이름 끝에 이유 태그를 붙임
 *                                  예) Null 1 (#Parent)(#Exp_Target)
 *                                  (컴포지션 전체를 정리할 때는 보이거나 소리 나는 레이어 이름은 그대로)
 *
 *  지우지 않는 경우 (태그)
 *   - 잠긴 레이어                                           (#Locked)
 *   - 눈(비디오)이 켜져 있어 화면에 보이는 레이어             (#Visible)
 *   - 오디오가 켜져 있어 소리가 나는 레이어                   (#Audio)
 *   - 다른 레이어의 부모                                     (#Parent)
 *   - 다른 레이어의 트랙 매트                                (#Matte)
 *   - 이펙트의 레이어 선택 항목에 지정됨 (매트 설정, 변위 맵 등)  (#<이펙트 이름> fx)
 *   - 이펙트가 아닌 곳의 레이어 선택 항목 / 환경 라이트 소스   (#Effect Target) (#Light Source)
 *   - 익스프레션이 이름·번호로 이 레이어를 가리킴             (#Exp_Target)
 *   - 지우면 레이어 번호가 밀려 익스프레션 결과가 바뀜         (#Exp_Index)
 *     (layer(3) 같은 번호 참조, index-1 같은 상대 참조, index 사용)
 *   - 익스프레션이 레이어 개수(numLayers)를 씀                (#Exp_NumLayers)
 *   - 익스프레션이 계산한 값으로 레이어를 찾음 (layer(i) 등)   (#Exp_Dynamic)
 *   - 에센셜 그래픽스(마스터 프로퍼티)에 등록된 프로퍼티가 있음 (#EGP)
 *   - 이펙트가 켜진 조정 레이어이고 아래에 보이는 레이어가 있음 (#Adjustment)
 *   - 3D 레이어를 비추는 라이트                              (#Light)
 *   - 3D 레이어의 시점을 정하는 카메라                        (#Camera)
 *   - 하나뿐인 솔로 레이어 (지우면 숨은 레이어가 다시 보임)     (#Solo)
 *  다른 컴포지션의 익스프레션(comp("이름").layer(...))까지 프로젝트 전체를 검사합니다.
 *  여러 개를 함께 지울 때는, 같이 지워지는 레이어끼리의 연결은 문제로 보지 않습니다.
 *  3D 레이어가 없어도 Particular · Element 3D 같은 이펙트가 있으면 카메라 · 라이트는 남깁니다.
 *
 *  설치 : After Effects 폴더의 Scripts/ScriptUI Panels 에 넣고 AE 재시작
 *         → 창(Window) 메뉴 맨 아래에서 이 스크립트를 열어 도킹
 *  실행 : 파일 > 스크립트 > 스크립트 파일 실행... 으로 바로 띄워도 됩니다.
 *  지원 : After Effects CC 2018 이상 (트랙 매트는 2023 이후 방식도 지원)
 *  주의 : 이 파일은 'UTF-8 (BOM)' 인코딩으로 저장해야 한글이 깨지지 않습니다.
 * ============================================================================
 */
(function (thisObj) {
  // UTF-8(BOM)로 읽히지 않으면 한글 문구가 모두 깨지므로, 안내만 하고 끝냅니다.
  if ('가'.length !== 1 || '가'.charCodeAt(0) !== 0xAC00) {
    alert('This script file was saved with the wrong text encoding.\n' +
      'Download the .jsx file again (do not copy & paste the code) or save it as "UTF-8 with BOM".\n\n' +
      '\uC2A4\uD06C\uB9BD\uD2B8 \uD30C\uC77C\uC758 \uC778\uCF54\uB529\uC774 \uC62C\uBC14\uB974\uC9C0 \uC54A\uC544 \uD55C\uAE00\uC774 \uAE68\uC84C\uC2B5\uB2C8\uB2E4.\n' +
      '\uCF54\uB4DC\uB97C \uBCF5\uC0AC\uD574 \uBD99\uC5EC\uB123\uC9C0 \uB9D0\uACE0 .jsx \uD30C\uC77C\uC744 \uADF8\uB300\uB85C \uB0B4\uB824\uBC1B\uAC70\uB098,\n' +
      '\uD3B8\uC9D1\uAE30\uC5D0\uC11C "UTF-8 (BOM)" \uD615\uC2DD\uC73C\uB85C \uB2E4\uC2DC \uC800\uC7A5\uD574 \uC8FC\uC138\uC694.');
    return;
  }

  var SCRIPT_NAME = 'COC Safe Delete';
  var SCRIPT_VERSION = 'v0.01';
  var TITLE = SCRIPT_NAME + ' ' + SCRIPT_VERSION;
  var EPS = 1e-6;
  var NL = ($.os && $.os.indexOf('Windows') !== -1) ? '\r\n' : '\n';

  // ===========================================================================
  //  작은 도우미 (ExtendScript 는 ES3 라서 trim, Array.indexOf 같은 것이 없습니다)
  // ===========================================================================
  function trim(s) { return String(s).replace(/^\s+|\s+$/g, ''); }

  function isWs(ch) {
    return ch === ' ' || ch === '\t' || ch === '\n' || ch === '\r' || ch === '\f' ||
      ch === '\u000B' || ch === '\u00A0' || ch === '\uFEFF';
  }

  // 익스프레션의 변수 이름에 쓰이는 글자 (한글 변수 이름도 포함)
  function isIdentChar(ch) {
    var c;
    if (!ch) return false;
    c = ch.charCodeAt(0);
    return (c >= 48 && c <= 57) || (c >= 65 && c <= 90) || (c >= 97 && c <= 122) ||
      c === 95 || c === 36 || (c > 127 && !isWs(ch));
  }

  function skipWsBack(s, i) {
    while (i >= 0 && isWs(s.charAt(i))) i--;
    return i;
  }

  function skipWsFwd(s, i) {
    while (i < s.length && isWs(s.charAt(i))) i++;
    return i;
  }

  function matchParenFwd(s, open) {
    var depth = 0, i, c;
    for (i = open; i < s.length; i++) {
      c = s.charAt(i);
      if (c === '(') depth++;
      else if (c === ')' && --depth === 0) return i;
    }
    return -1;
  }

  function matchParenBack(s, close) {
    var depth = 0, i, c;
    for (i = close; i >= 0; i--) {
      c = s.charAt(i);
      if (c === ')') depth++;
      else if (c === '(' && --depth === 0) return i;
    }
    return -1;
  }

  function inRanges(ranges, pos) {
    for (var i = 0; i < ranges.length; i++) {
      if (pos > ranges[i][0] && pos < ranges[i][1]) return true;
    }
    return false;
  }

  function joinPath(names, last) {
    return names.length ? names.join(' > ') + ' > ' + last : last;
  }

  // 레이어를 구별하는 키 (삭제하기 전의 번호 기준)
  function layerKey(ly) { return ly.containingComp.id + ':' + ly.index; }

  function label(ly) { return '"' + ly.name + '"(#' + ly.index + ')'; }

  function sampleLabels(list) {
    var out = [], i, max = Math.min(3, list.length), s;
    for (i = 0; i < max; i++) out.push(label(list[i]));
    s = out.join(', ');
    if (list.length > max) s += ' 외 ' + (list.length - max) + '개';
    return s;
  }

  // 컴포지션 안에서 레이어가 실제로 있는 시간 구간 [a, b]
  function timeRange(ly, dur) {
    var a = Math.min(ly.inPoint, ly.outPoint), b = Math.max(ly.inPoint, ly.outPoint);
    return { a: Math.max(0, a), b: Math.min(dur, b) };
  }

  function overlaps(r1, r2) { return r1.a < r2.b - EPS && r2.a < r1.b - EPS; }

  function overlapsAny(r, list) {
    for (var i = 0; i < list.length; i++) if (overlaps(r, list[i])) return true;
    return false;
  }

  // 눈(비디오 스위치)이 켜져 있고 픽셀을 그리는 레이어 (널은 그리지 않음)
  function isRendered(ly) {
    try {
      return (ly instanceof AVLayer) && ly.enabled && ly.hasVideo && !ly.nullLayer;
    } catch (e) {
      return false;
    }
  }

  function isSolo(ly) {
    try { return !!ly.solo; } catch (e) { return false; }
  }

  function kindLabel(ly) {
    var src = null;
    if (ly instanceof TextLayer) return '텍스트';
    if (ly instanceof ShapeLayer) return '셰이프';
    try { src = ly.source; } catch (e) { src = null; }
    if (src instanceof CompItem) return '프리컴프';
    try {
      if (src && src.mainSource instanceof SolidSource) return '솔리드';
      if (src && src.mainSource && src.mainSource.isStill) return '이미지';
    } catch (e) {}
    return '비디오';
  }

  function matteLabel(type) {
    if (type === TrackMatteType.ALPHA) return '알파 매트';
    if (type === TrackMatteType.ALPHA_INVERTED) return '알파 반전 매트';
    if (type === TrackMatteType.LUMA) return '루마 매트';
    if (type === TrackMatteType.LUMA_INVERTED) return '루마 반전 매트';
    return '트랙 매트';
  }

  function hasActiveEffects(ly) {
    var fx, i;
    try {
      fx = ly.property('ADBE Effect Parade');
      for (i = 1; fx && i <= fx.numProperties; i++) {
        if (fx.property(i).enabled) return true;
      }
    } catch (e) {}
    return false;
  }

  function acceptsLights(ly) {
    var p;
    try {
      p = ly.property('ADBE Material Options Group').property('ADBE Accepts Lights');
      return !p || p.value !== 0;
    } catch (e) {
      return true;
    }
  }

  // 모든 하위 프로퍼티를 돌면서 visit(property, 상위 그룹 이름들, 속한 이펙트 이름) 호출
  function walkProps(grp, names, effName, visit) {
    var n = 0, isFx = false, i, p, pt, nm;
    try { n = grp.numProperties; } catch (e) { return; }
    try { isFx = grp.matchName === 'ADBE Effect Parade'; } catch (e) {}
    for (i = 1; i <= n; i++) {
      try {
        p = grp.property(i);
        pt = p.propertyType;
      } catch (e) {
        continue;
      }
      if (!p) continue;
      if (pt === PropertyType.PROPERTY) {
        visit(p, names, effName);
      } else {
        try { nm = p.name; } catch (e) { nm = ''; }
        names.push(nm);
        walkProps(p, names, isFx ? nm : effName, visit);
        names.pop();
      }
    }
  }

  function propertyPath(p) {
    var names = [];
    try {
      while (p && p.propertyDepth > 0) {
        names.unshift(p.name);
        p = p.parentProperty;
      }
    } catch (e) {}
    return names.join(' > ');
  }

  // ===========================================================================
  //  익스프레션 읽기
  // ===========================================================================

  // 주석을 공백으로 바꾼 사본(code)과, 문자열·정규식 내용까지 공백으로 가린 사본(bare)을 만듭니다.
  // 두 사본은 길이가 같아서 bare 에서 찾은 위치를 code 에서 그대로 쓸 수 있습니다.
  function prepareExpression(src) {
    var code = [], bare = [], n = src.length, i = 0, prev = '', c, c2, d, end, inClass;
    while (i < n) {
      c = src.charAt(i);
      c2 = i + 1 < n ? src.charAt(i + 1) : '';
      if (c === '/' && c2 === '/') {
        while (i < n && src.charAt(i) !== '\n' && src.charAt(i) !== '\r') {
          code.push(' ');
          bare.push(' ');
          i++;
        }
        continue;
      }
      if (c === '/' && c2 === '*') {
        end = src.indexOf('*/', i + 2);
        end = end < 0 ? n : end + 2;
        for (; i < end; i++) {
          d = src.charAt(i);
          d = (d === '\n' || d === '\r') ? d : ' ';
          code.push(d);
          bare.push(d);
        }
        continue;
      }
      if (c === '"' || c === '\'' || c === '`') {
        code.push(c);
        bare.push(c);
        i++;
        while (i < n) {
          d = src.charAt(i);
          if (d === '\\' && i + 1 < n) {
            code.push(d, src.charAt(i + 1));
            bare.push(' ', ' ');
            i += 2;
            continue;
          }
          if (d === c) {
            code.push(d);
            bare.push(d);
            i++;
            break;
          }
          if ((d === '\n' || d === '\r') && c !== '`') break;
          code.push(d);
          bare.push((d === '\n' || d === '\r') ? d : ' ');
          i++;
        }
        prev = c;
        continue;
      }
      if (c === '/' && (prev === '' || '(,=:[!&|?{};+-*%<>~^'.indexOf(prev) !== -1)) {
        // 정규식 리터럴 /.../
        code.push(c);
        bare.push(c);
        i++;
        inClass = false;
        while (i < n) {
          d = src.charAt(i);
          if (d === '\\' && i + 1 < n) {
            code.push(d, src.charAt(i + 1));
            bare.push(' ', ' ');
            i += 2;
            continue;
          }
          if (d === '\n' || d === '\r') break;
          if (d === '[') inClass = true;
          else if (d === ']') inClass = false;
          else if (d === '/' && !inClass) {
            code.push(d);
            bare.push(d);
            i++;
            break;
          }
          code.push(d);
          bare.push(' ');
          i++;
        }
        prev = ')';
        continue;
      }
      code.push(c);
      bare.push(c);
      if (!isWs(c)) prev = c;
      i++;
    }
    return { code: code.join(''), bare: bare.join('') };
  }

  function unescapeJs(s) {
    return s.replace(/\\(u[0-9a-fA-F]{4}|x[0-9a-fA-F]{2}|[\s\S])/g, function (m, e) {
      var h = e.charAt(0);
      if (e.length > 1 && (h === 'u' || h === 'x')) return String.fromCharCode(parseInt(e.substring(1), 16));
      if (e === 'n') return '\n';
      if (e === 't') return '\t';
      if (e === 'r') return '\r';
      return e;
    });
  }

  // layer( ... ) 괄호 안의 내용 분류
  //  name: "이름"   abs: 3   rel: index-1, thisLayer, 1   dyn: 그 밖의 계산식
  function classifyLayerArg(arg) {
    var s = trim(arg), m;
    m = s.match(/^"((?:[^"\\]|\\[\s\S])*)"$/) || s.match(/^'((?:[^'\\]|\\[\s\S])*)'$/) ||
      s.match(/^`((?:[^`\\$]|\\[\s\S])*)`$/);
    if (m) return { k: 'name', name: unescapeJs(m[1]) };
    if (/^\d+$/.test(s)) return { k: 'abs', n: parseInt(s, 10) };
    m = s.match(/^(?:thisLayer\s*\.\s*)?index(?:\s*([+\-])\s*(\d+))?$/);
    if (m) return { k: 'rel', off: m[1] ? (m[1] === '-' ? -1 : 1) * parseInt(m[2], 10) : 0 };
    m = s.match(/^(\d+)\s*\+\s*(?:thisLayer\s*\.\s*)?index$/);
    if (m) return { k: 'rel', off: parseInt(m[1], 10) };
    m = s.match(/^thisLayer\s*,\s*([+\-]?)\s*(\d+)$/);
    if (m) return { k: 'rel', off: (m[1] === '-' ? -1 : 1) * parseInt(m[2], 10) };
    return { k: 'dyn' };
  }

  function findCompByName(ctx, name) {
    if (name === ctx.C.name) return ctx.C; // 이름이 같은 컴포지션이 여럿이면 지금 검사하는 쪽으로 (안전한 쪽)
    return ctx.comps.hasOwnProperty('c_' + name) ? ctx.comps['c_' + name] : null;
  }

  // 익스프레션의 layer("이름") 은 같은 이름 중 가장 위 레이어를 가리킵니다.
  function firstLayerIndexByName(ctx, comp, name) {
    var map = ctx.names['k' + comp.id], i;
    if (!map) {
      map = {};
      for (i = comp.numLayers; i >= 1; i--) map['n_' + comp.layer(i).name] = i;
      ctx.names['k' + comp.id] = map;
    }
    return map.hasOwnProperty('n_' + name) ? map['n_' + name] : 0;
  }

  function layerMember(ly, id) {
    try {
      if (id === 'parent') return ly.parent ? { t: 'layer', layer: ly.parent, self: false } : null;
      if (id === 'source' && ly.source && ly.source instanceof CompItem) return { t: 'comp', comp: ly.source };
    } catch (e) {}
    return null;
  }

  // bare 의 end 위치에서 끝나는 식(점 앞부분)이 무엇을 가리키는지 거꾸로 읽어 냅니다.
  // 결과: { t: 'comp', comp } / { t: 'layer', layer, self } / null(알 수 없음)
  function resolveBefore(ex, end, depth) {
    var s = ex.bare, j, ch, st, id, q, owner, op, fe, fs, fname, arg, hasOwner, comp, a, idx;
    if (depth > 16) return null;
    j = skipWsBack(s, end);
    if (j < 0) return null;
    ch = s.charAt(j);
    if (isIdentChar(ch)) {
      st = j;
      while (st > 0 && isIdentChar(s.charAt(st - 1))) st--;
      id = s.substring(st, j + 1);
      q = skipWsBack(s, st - 1);
      if (q >= 0 && s.charAt(q) === '.') {
        owner = resolveBefore(ex, q - 1, depth + 1);
        return (owner && owner.t === 'layer') ? layerMember(owner.layer, id) : null;
      }
      if (id === 'thisComp') return { t: 'comp', comp: ex.comp };
      if (id === 'thisLayer') return { t: 'layer', layer: ex.layer, self: true };
      return layerMember(ex.layer, id); // 그냥 parent, source 라고 쓰면 thisLayer 의 것
    }
    if (ch !== ')') return null;
    op = matchParenBack(s, j);
    if (op < 0) return null;
    fe = skipWsBack(s, op - 1);
    if (fe < 0 || !isIdentChar(s.charAt(fe))) return null;
    fs = fe;
    while (fs > 0 && isIdentChar(s.charAt(fs - 1))) fs--;
    fname = s.substring(fs, fe + 1);
    arg = ex.code.substring(op + 1, j);
    q = skipWsBack(s, fs - 1);
    hasOwner = q >= 0 && s.charAt(q) === '.';
    if (fname === 'comp' && !hasOwner) {
      a = classifyLayerArg(arg);
      comp = a.k === 'name' ? findCompByName(ex.ctx, a.name) : null;
      return comp ? { t: 'comp', comp: comp } : null;
    }
    if (fname !== 'layer' || !hasOwner) return null;
    owner = resolveBefore(ex, q - 1, depth + 1);
    if (!owner || owner.t !== 'comp') return null;
    comp = owner.comp;
    a = classifyLayerArg(arg);
    idx = 0;
    if (a.k === 'name') idx = firstLayerIndexByName(ex.ctx, comp, a.name);
    else if (a.k === 'abs') idx = a.n;
    else if (a.k === 'rel' && comp.id === ex.comp.id) idx = ex.layer.index + a.off;
    if (idx < 1 || idx > comp.numLayers) return null;
    return { t: 'layer', layer: comp.layer(idx), self: comp.id === ex.comp.id && idx === ex.layer.index };
  }

  // 컴포지션 E 의 레이어 X 에 걸린 익스프레션에서, 검사 중인 컴포지션(ctx.C)과 관련된 참조만 뽑습니다.
  //  name  : layer("이름")              (idx = 그 이름이 가리키는 레이어 번호)
  //  abs   : layer(3)
  //  rel   : layer(index-1), layer(thisLayer, 1)  (x = X 번호, t = 가리키는 번호)
  //  dyn   : layer(i) 처럼 계산된 값
  //  count : numLayers
  //  own   : X 자신의 index
  //  lidx  : 다른 레이어의 .index
  function parseExpressionRefs(text, X, E, ctx) {
    var C = ctx.C, pre = prepareExpression(text), s = pre.bare;
    var ex = { bare: s, code: pre.code, comp: E, layer: X, ctx: ctx };
    var inC = E.id === C.id;
    // 주인을 알 수 없는 layer(...) (변수에 담은 컴포지션 등) 는 같은 컴포지션이거나
    // 검사 중인 컴포지션 이름이 문자열로 들어 있을 때만 관련 있다고 봅니다.
    var loose = inC || pre.code.indexOf('"' + C.name + '"') !== -1 || pre.code.indexOf('\'' + C.name + '\'') !== -1;
    // ES3 는 정규식 리터럴 하나를 계속 같이 써서 lastIndex 가 남을 수 있으므로 매번 새로 만듭니다.
    var refs = [], skip = [], re = new RegExp('[A-Za-z_$][A-Za-z0-9_$]*', 'g');
    var m, nm, p, q, isMember, o, cl, owner, K, a, idx;
    while ((m = re.exec(s)) !== null) {
      nm = m[0];
      if (nm !== 'layer' && nm !== 'index' && nm !== 'numLayers') continue;
      p = m.index;
      if (p > 0 && isIdentChar(s.charAt(p - 1))) continue;
      q = skipWsBack(s, p - 1);
      isMember = q >= 0 && s.charAt(q) === '.' && !(q > 0 && s.charAt(q - 1) === '.');
      if (nm === 'layer') {
        o = skipWsFwd(s, p + nm.length);
        if (s.charAt(o) !== '(') continue;
        cl = matchParenFwd(s, o);
        if (cl < 0) continue;
        owner = isMember ? resolveBefore(ex, q - 1, 0) : null;
        if (owner && owner.t !== 'comp') continue;
        K = owner ? owner.comp : null;
        a = classifyLayerArg(pre.code.substring(o + 1, cl));
        if (a.k === 'rel') skip.push([o, cl]);
        if (!(K ? K.id === C.id : loose)) continue;
        if (a.k === 'name') {
          idx = firstLayerIndexByName(ctx, C, a.name);
          if (idx) refs.push({ k: 'name', idx: idx });
        } else if (a.k === 'abs') {
          refs.push({ k: 'abs', n: a.n });
        } else if (a.k === 'rel') {
          if (inC && (!K || K.id === E.id)) refs.push({ k: 'rel', x: X.index, t: X.index + a.off, off: a.off });
          else refs.push({ k: 'abs', n: X.index + a.off });
        } else {
          refs.push({ k: 'dyn' });
        }
      } else if (nm === 'numLayers') {
        if (!isMember) continue;
        owner = resolveBefore(ex, q - 1, 0);
        if (owner ? (owner.t === 'comp' && owner.comp.id === C.id) : loose) refs.push({ k: 'count' });
      } else {
        if (inRanges(skip, p)) continue;
        if (!isMember) {
          if (inC) refs.push({ k: 'own', x: X.index });
          continue;
        }
        owner = resolveBefore(ex, q - 1, 0);
        if (!owner || owner.t !== 'layer' || owner.layer.containingComp.id !== C.id) continue;
        if (owner.self) refs.push({ k: 'own', x: owner.layer.index });
        else refs.push({ k: 'lidx', y: owner.layer.index, yName: owner.layer.name });
      }
    }
    return refs;
  }

  function relText(off) {
    return 'layer(index' + (off < 0 ? '-' : '+') + Math.abs(off) + ')';
  }

  // 참조 하나가 li 번 레이어를 지울 때 영향을 받는지 → { tag, text } 또는 null
  function expressionImpact(ref, li) {
    var lo, hi;
    if (ref.k === 'name') {
      return ref.idx === li ? { tag: 'Exp_Target', text: '익스프레션의 타겟으로 사용되고 있습니다.' } : null;
    }
    if (ref.k === 'abs') {
      if (ref.n === li) return { tag: 'Exp_Target', text: '익스프레션의 타겟으로 사용되고 있습니다. (layer(' + ref.n + ') 번호로 참조)' };
      if (ref.n > li) {
        return { tag: 'Exp_Index', text: '익스프레션이 layer(' + ref.n + ') 처럼 번호로 레이어를 가리키고 있어, ' +
          '지우면 번호가 밀려 다른 레이어를 가리키게 됩니다.' };
      }
      return null;
    }
    if (ref.k === 'rel') {
      if (ref.t === li) return { tag: 'Exp_Target', text: '익스프레션의 타겟으로 사용되고 있습니다. (' + relText(ref.off) + ' 상대 번호로 참조)' };
      lo = Math.min(ref.x, ref.t);
      hi = Math.max(ref.x, ref.t);
      if (li > lo && li < hi) {
        return { tag: 'Exp_Index', text: '익스프레션이 ' + relText(ref.off) + ' 처럼 상대 번호로 레이어를 가리키고 있어, ' +
          '지우면 다른 레이어를 가리키게 됩니다.' };
      }
      return null;
    }
    if (ref.k === 'own') {
      return ref.x > li ? { tag: 'Exp_Index', text: '익스프레션이 자기 레이어 번호(index)를 쓰고 있어, 지우면 번호가 바뀌어 결과가 달라집니다.' } : null;
    }
    if (ref.k === 'lidx') {
      return ref.y > li ? { tag: 'Exp_Index', text: '익스프레션이 "' + ref.yName + '" 레이어의 번호(index)를 쓰고 있어, 지우면 결과가 달라집니다.' } : null;
    }
    if (ref.k === 'count') {
      return { tag: 'Exp_NumLayers', text: '익스프레션이 레이어 개수(numLayers)를 쓰고 있어, 지우면 결과가 달라집니다.' };
    }
    if (ref.k === 'dyn') {
      return { tag: 'Exp_Dynamic', text: '익스프레션이 계산한 값으로 레이어를 찾고 있어(layer(변수) 등), 지우면 결과가 달라질 수 있습니다.' };
    }
    return null;
  }

  // ===========================================================================
  //  프로젝트 전체 검사
  //  프로젝트를 한 번만 훑어서 익스프레션과 레이어 선택 항목을 모아 두고(scanProject),
  //  컴포지션마다 그 목록에서 필요한 참조만 뽑아 씁니다(contextFor).
  // ===========================================================================
  function scanProject(targets) {
    var raw = { comps: {}, exprs: [], layerProps: [] }, want = {}, comps = [], i, j, it;
    for (i = 0; i < targets.length; i++) want['k' + targets[i].id] = true;
    for (i = 1; i <= app.project.numItems; i++) {
      it = app.project.item(i);
      if (!(it instanceof CompItem)) continue;
      comps.push(it);
      if (!raw.comps.hasOwnProperty('c_' + it.name)) raw.comps['c_' + it.name] = it;
    }
    for (i = 0; i < comps.length; i++) {
      for (j = 1; j <= comps[i].numLayers; j++) scanLayer(comps[i].layer(j), comps[i], raw, want['k' + comps[i].id] === true);
    }
    return raw;
  }

  function scanLayer(X, E, raw, wantLayerProps) {
    walkProps(X, [], null, function (p, names, effName) {
      var vt = null, ex = '', on = true;
      if (wantLayerProps) {
        try { vt = p.propertyValueType; } catch (e) { vt = null; }
        if (vt === PropertyValueType.LAYER_INDEX) {
          raw.layerProps.push({ user: X, comp: E, prop: p, effName: effName, propName: p.name, path: joinPath(names, p.name), dead: false });
        }
      }
      try { ex = p.expression; } catch (e) { ex = ''; }
      if (!ex || (ex.indexOf('layer') === -1 && ex.indexOf('index') === -1 && ex.indexOf('numLayers') === -1)) return;
      try { on = p.expressionEnabled; } catch (e) { on = true; }
      raw.exprs.push({ user: X, comp: E, prop: p, text: ex, path: joinPath(names, p.name), off: !on, dead: false });
    });
  }

  function pushDep(map, idx, item) {
    if (!map['t' + idx]) map['t' + idx] = [];
    map['t' + idx].push(item);
  }

  // 컴포지션 C 를 검사할 때 쓰는 참조 목록 (지금 레이어 번호 기준)
  function contextFor(C, raw) {
    var ctx = { C: C, comps: raw.comps, names: {}, exprs: [], layerRefs: [], egp: [], parents: {}, mattes: {}, lightSources: {} };
    var n = C.numLayers, i, r, refs, v, X, tml;
    for (i = 0; i < raw.exprs.length; i++) {
      r = raw.exprs[i];
      if (r.dead) continue;
      // 다른 컴포지션의 익스프레션은 이 컴포지션 이름이나 .source 가 들어 있을 때만 관련이 있습니다.
      if (r.comp.id !== C.id && r.text.indexOf(C.name) === -1 && r.text.indexOf('source') === -1) continue;
      refs = parseExpressionRefs(r.text, r.user, r.comp, ctx);
      if (refs.length) {
        ctx.exprs.push({ user: r.user, key: layerKey(r.user), comp: r.comp, inC: r.comp.id === C.id, prop: r.prop, path: r.path, off: r.off, refs: refs });
      }
    }
    for (i = 0; i < raw.layerProps.length; i++) {
      r = raw.layerProps[i];
      if (r.dead || r.comp.id !== C.id) continue;
      try { v = r.prop.value; } catch (e) { v = 0; }
      if (v > 0) ctx.layerRefs.push({ user: r.user, key: layerKey(r.user), idx: v, effName: r.effName, propName: r.propName, path: r.path });
    }
    // 부모 · 트랙 매트 · 환경 라이트 소스: 누가 어느 번호의 레이어를 쓰는지
    for (i = 1; i <= n; i++) {
      X = C.layer(i);
      try {
        if (X.parent) pushDep(ctx.parents, X.parent.index, X);
      } catch (e) {}
      if (X instanceof AVLayer) {
        try {
          tml = X.trackMatteLayer; // AE 2023(23.0) 이상: 매트 레이어를 직접 알려 줌
          if (tml !== undefined) {
            if (tml) pushDep(ctx.mattes, tml.index, { user: X, type: X.trackMatteType });
          } else if (i > 1 && X.trackMatteType !== TrackMatteType.NO_TRACK_MATTE) {
            pushDep(ctx.mattes, i - 1, { user: X, type: X.trackMatteType }); // 이전 버전: 바로 위 레이어가 매트
          }
        } catch (e) {}
      }
      if (X instanceof LightLayer) {
        try {
          v = X.lightSource; // AE 2024 이상 환경 라이트
          if (v && v.containingComp && v.containingComp.id === C.id) pushDep(ctx.lightSources, v.index, X);
        } catch (e) {}
      }
    }
    collectEssentialProperties(ctx);
    return ctx;
  }

  // 에센셜 그래픽스 패널에 올린 프로퍼티(마스터 프로퍼티)의 원래 레이어를 찾습니다. (AE 2022 이상)
  // 이 컴포지션을 쓰는 레이어가 없으면 잠깐 임시 컴포지션에 넣어서 읽고 바로 지웁니다.
  function collectEssentialProperties(ctx) {
    var C = ctx.C, count = 0, inst = null, tmp = null, users, i, j, ly, grp = null;
    try { count = C.motionGraphicsTemplateControllerCount || 0; } catch (e) { count = 0; }
    if (!count) return;
    try {
      users = C.usedIn;
      for (i = 0; i < users.length && !inst; i++) {
        for (j = 1; j <= users[i].numLayers; j++) {
          ly = users[i].layer(j);
          if (ly instanceof AVLayer && ly.source && ly.source.id === C.id) {
            inst = ly;
            break;
          }
        }
      }
    } catch (e) {}
    try {
      if (!inst) {
        tmp = app.project.items.addComp('COC Safe Delete (temp)', C.width, C.height, C.pixelAspect, C.duration, C.frameRate);
        inst = tmp.layers.add(C);
      }
      try { grp = inst.essentialProperty; } catch (e) { grp = null; }
      if (!grp) {
        try { grp = inst.property('ADBE Layer Overrides'); } catch (e) { grp = null; }
      }
      if (grp) {
        walkProps(grp, [], null, function (p) {
          var src = null, srcLayer = null, srcPath = '';
          try { src = p.essentialPropertySource; } catch (e) { src = null; }
          if (!src) return;
          try {
            if (src.containingComp) {
              srcLayer = src; // 미디어 교체는 레이어 자체
            } else {
              srcLayer = src.propertyGroup(src.propertyDepth);
              srcPath = propertyPath(src);
            }
          } catch (e) {
            srcLayer = null;
          }
          if (srcLayer && srcLayer.containingComp.id === C.id) ctx.egp.push({ idx: srcLayer.index, ctrl: p.name, path: srcPath });
        });
      }
    } catch (e) {
    } finally {
      if (tmp) {
        try { tmp.remove(); } catch (e) {}
      }
    }
  }

  // ===========================================================================
  //  문제(이유) 목록
  //  hard  : 무조건 지우면 안 됨
  //  users : 이 레이어를 쓰는 레이어들 — 모두 함께 지워질 때만 괜찮음
  // ===========================================================================
  function hardIssue(cat, tag, text) {
    return { cat: cat, tag: tag, text: text, users: null, keys: null };
  }

  function userIssue(cat, tag, user, head, tail) {
    return { cat: cat, tag: tag, users: [user], keys: [layerKey(user)], head: head, tail: tail };
  }

  function groupIssue(cat, tag, users, fmt) {
    var keys = [], i;
    for (i = 0; i < users.length; i++) keys.push(layerKey(users[i]));
    return { cat: cat, tag: tag, users: users, keys: keys, fmt: fmt };
  }

  function isWaived(issue, del) {
    var i;
    if (!issue.keys) return false;
    for (i = 0; i < issue.keys.length; i++) {
      if (del[issue.keys[i]] !== true) return false;
    }
    return true;
  }

  // 삭제가 끝난 뒤에 부르므로, 남아 있는 레이어의 지금 번호로 적습니다.
  function issueText(issue, del) {
    var alive = [], i;
    if (!issue.keys) return issue.text;
    for (i = 0; i < issue.users.length; i++) {
      if (del[issue.keys[i]] !== true) alive.push(issue.users[i]);
    }
    if (issue.fmt) return issue.fmt.split('{n}').join(String(alive.length)).split('{list}').join(sampleLabels(alive));
    return issue.head + label(alive.length ? alive[0] : issue.users[0]) + issue.tail;
  }

  function cleanTag(s) { return trim(String(s).replace(/[()]/g, ' ').replace(/\s+/g, ' ')); }

  function activeCameraSegments(C, cam, own, dur) {
    var cover = [], segs = [], i, X, r, cur;
    for (i = 1; i < cam.index; i++) {
      X = C.layer(i);
      if (X instanceof CameraLayer && X.enabled) {
        r = timeRange(X, dur);
        if (r.b - r.a > EPS) cover.push(r);
      }
    }
    cover.sort(function (a, b) { return a.a - b.a; });
    cur = own.a;
    for (i = 0; i < cover.length && cur < own.b - EPS; i++) {
      if (cover[i].b <= cur + EPS) continue;
      if (cover[i].a > cur + EPS) segs.push({ a: cur, b: Math.min(cover[i].a, own.b) });
      if (cover[i].b > cur) cur = cover[i].b;
    }
    if (cur < own.b - EPS) segs.push({ a: cur, b: own.b });
    return segs;
  }

  // 2D 레이어에서도 컴포지션 카메라 · 라이트를 읽는 이펙트 (Particular, Element 3D, 카드 댄스, 셰터 등)
  // 어도비 기본 이펙트(ADBE …, CC …)는 대부분 읽지 않으므로, 그 밖의 이펙트와 카드 · 셰터 · 커스틱만 의심합니다.
  function cameraAwareEffect(ly) {
    var fx, i, ef, mn;
    try {
      fx = ly.property('ADBE Effect Parade');
      for (i = 1; fx && i <= fx.numProperties; i++) {
        ef = fx.property(i);
        if (!ef.enabled) continue;
        mn = String(ef.matchName);
        if ((mn.indexOf('ADBE ') !== 0 && mn.indexOf('CC ') !== 0) || /Card|Shatter|Caustics/.test(mn)) return ef.name;
      }
    } catch (e) {}
    return '';
  }

  // 3D 레이어가 없을 때, 카메라 · 라이트를 읽을 수 있는 이펙트를 쓰는 레이어
  function pluginUsers(C, L, ranges, dur) {
    var out = { list: [], fx: '' }, i, X, name;
    for (i = 1; i <= C.numLayers; i++) {
      if (i === L.index) continue;
      X = C.layer(i);
      if (!isRendered(X) || !overlapsAny(timeRange(X, dur), ranges)) continue;
      name = cameraAwareEffect(X);
      if (name) {
        out.list.push(X);
        if (!out.fx) out.fx = name;
      }
    }
    return out;
  }

  // 지우는 대상으로 골랐어도 반드시 남는 레이어
  function surelyStays(X, selected) {
    try {
      return !selected[layerKey(X)] || X.locked || (isRendered(X) && !X.adjustmentLayer) ||
        ((X instanceof AVLayer) && X.hasAudio && X.audioEnabled);
    } catch (e) {
      return true;
    }
  }

  // quick: 여러 레이어를 한꺼번에 정리할 때, 보이거나 소리 나는 레이어는 다른 이유를 따지지 않음
  function analyzeLayer(L, ctx, selected, quick) {
    var C = ctx.C, li = L.index, key = layerKey(L), n = C.numLayers, dur = C.duration;
    var issues = [], seen = {}, live = false, i, j, X, lr, rec, head, hit, own, on = false, list, segs, plug, other, hidden;

    function add(issue) {
      var sig = issue.tag + '|' + (issue.text || issue.tail || issue.fmt) + '|' + (issue.keys ? issue.keys.join(',') : '');
      if (seen[sig]) return;
      seen[sig] = true;
      issues.push(issue);
    }

    // 1. 잠금
    if (L.locked) add(hardIssue('잠금', 'Locked', '잠긴(Lock) 레이어입니다. 잠금을 풀고 다시 시도하세요.'));

    // 2. 화면에 보이거나 소리가 나는 레이어
    if (L instanceof AVLayer) {
      if (isRendered(L) && !L.adjustmentLayer) {
        live = true;
        add(hardIssue('화면 표시', 'Visible', '눈(비디오 스위치)이 켜져 있어 화면에 보이는 ' + kindLabel(L) + ' 레이어입니다.' +
          (L.guideLayer ? ' (가이드 레이어)' : '')));
      }
      if (L.hasAudio && L.audioEnabled) {
        live = true;
        add(hardIssue('오디오', 'Audio', '오디오 스위치가 켜져 있어 소리가 나는 레이어입니다.'));
      }
    }
    if (quick && live) return issues;

    // 3. 부모 / 트랙 매트 / 환경 라이트 소스
    list = ctx.parents['t' + li] || [];
    for (i = 0; i < list.length; i++) add(userIssue('부모', 'Parent', list[i], '', ' 레이어의 부모입니다.'));
    list = ctx.mattes['t' + li] || [];
    for (i = 0; i < list.length; i++) {
      add(userIssue('트랙 매트', 'Matte', list[i].user, '', ' 레이어의 트랙 매트입니다. (' + matteLabel(list[i].type) + ')'));
    }
    list = ctx.lightSources['t' + li] || [];
    for (i = 0; i < list.length; i++) add(userIssue('라이트 소스', 'Light Source', list[i], '', ' 라이트의 소스 레이어로 쓰이고 있습니다.'));

    // 4. 이펙트 등에서 레이어를 고르는 항목 (매트 설정, 변위 맵, 레이어 컨트롤 …)
    for (i = 0; i < ctx.layerRefs.length; i++) {
      lr = ctx.layerRefs[i];
      if (lr.idx !== li || lr.key === key) continue;
      if (lr.effName) {
        add(userIssue('이펙트', cleanTag(lr.effName) + ' fx', lr.user, '',
          ' 레이어의 "' + lr.effName + '" 이펙트 타겟으로 설정되어 있습니다. ("' + lr.propName + '")'));
      } else if (lr.user instanceof LightLayer) {
        add(userIssue('라이트 소스', 'Light Source', lr.user, '', ' 라이트의 소스 레이어로 쓰이고 있습니다.'));
      } else {
        add(userIssue('레이어 참조', 'Effect Target', lr.user, '', ' 레이어의 "' + lr.path + '" 항목에 레이어로 지정되어 있습니다.'));
      }
    }

    // 5. 익스프레션 (프로젝트 전체)
    for (i = 0; i < ctx.exprs.length; i++) {
      rec = ctx.exprs[i];
      if (rec.key === key) continue;
      head = rec.inC ? '' : '[' + rec.comp.name + '] 컴포지션의 ';
      for (j = 0; j < rec.refs.length; j++) {
        hit = expressionImpact(rec.refs[j], li);
        if (hit) {
          add(userIssue('익스프레션', hit.tag, rec.user, head,
            ' 레이어의 "' + rec.path + '" 프로퍼티 ' + hit.text + (rec.off ? ' (지금은 꺼져 있는 익스프레션)' : '')));
        }
      }
    }

    // 6. 에센셜 그래픽스 (마스터 프로퍼티)
    for (i = 0; i < ctx.egp.length; i++) {
      if (ctx.egp[i].idx !== li) continue;
      add(hardIssue('에센셜 그래픽스', 'EGP', ctx.egp[i].path ?
        '이 레이어의 "' + ctx.egp[i].path + '" 프로퍼티가 에센셜 그래픽스 패널에 "' + ctx.egp[i].ctrl + '" (마스터 프로퍼티)로 등록되어 있습니다.' :
        '이 레이어가 에센셜 그래픽스 패널에 "' + ctx.egp[i].ctrl + '" (미디어 교체)로 등록되어 있습니다.'));
    }

    // 7. 다른 레이어의 모습을 바꾸는 레이어 (조정 레이어 / 라이트 / 카메라)
    own = timeRange(L, dur);
    try { on = L.enabled; } catch (e) { on = false; }
    if (on && own.b - own.a > EPS) {
      list = [];
      if (L instanceof AVLayer && L.adjustmentLayer && hasActiveEffects(L)) {
        for (i = li + 1; i <= n; i++) {
          X = C.layer(i);
          if (isRendered(X) && overlaps(timeRange(X, dur), own)) list.push(X);
        }
        if (list.length) add(groupIssue('조정 레이어', 'Adjustment', list, '이펙트가 켜진 조정 레이어로, 아래 레이어 {n}개({list})의 모습을 바꾸고 있습니다.'));
      } else if (L instanceof LightLayer) {
        for (i = 1; i <= n; i++) {
          if (i === li) continue;
          X = C.layer(i);
          if (isRendered(X) && X.threeDLayer && acceptsLights(X) && overlaps(timeRange(X, dur), own)) list.push(X);
        }
        if (list.length) {
          add(groupIssue('라이트', 'Light', list, '라이트로서 3D 레이어 {n}개({list})를 비추고 있습니다.'));
        } else {
          plug = pluginUsers(C, L, [own], dur);
          if (plug.list.length) {
            add(groupIssue('라이트', 'Light', plug.list, '3D 레이어는 없지만, 컴포지션 라이트를 쓸 수 있는 이펙트("' + plug.fx +
              '" 등)가 있는 레이어 {n}개({list})가 있습니다.'));
          }
        }
      } else if (L instanceof CameraLayer) {
        segs = activeCameraSegments(C, L, own, dur);
        for (i = 1; segs.length && i <= n; i++) {
          X = C.layer(i);
          if (isRendered(X) && X.threeDLayer && overlapsAny(timeRange(X, dur), segs)) list.push(X);
        }
        if (list.length) {
          add(groupIssue('카메라', 'Camera', list, '컴포지션 카메라로서 3D 레이어 {n}개({list})의 시점을 정하고 있습니다.'));
        } else if (segs.length) {
          plug = pluginUsers(C, L, segs, dur);
          if (plug.list.length) {
            add(groupIssue('카메라', 'Camera', plug.list, '3D 레이어는 없지만, 컴포지션 카메라를 쓸 수 있는 이펙트("' + plug.fx +
              '" 등)가 있는 레이어 {n}개({list})가 있습니다.'));
          }
        }
      }
    }

    // 8. 솔로: 남는 솔로 레이어가 없으면, 지울 때 숨어 있던 레이어가 다시 보입니다.
    if (isSolo(L)) {
      other = false;
      hidden = 0;
      for (i = 1; i <= n; i++) {
        if (i === li) continue;
        X = C.layer(i);
        if (isSolo(X)) {
          if (surelyStays(X, selected)) {
            other = true;
            break;
          }
        } else if (isRendered(X) && surelyStays(X, selected)) {
          hidden++;
        }
      }
      if (!other && hidden) {
        add(hardIssue('솔로', 'Solo', '솔로(Solo)가 켜진 레이어입니다. 지우면 솔로가 풀려 숨어 있던 레이어 ' + hidden + '개가 다시 보이게 됩니다.'));
      }
    }
    return issues;
  }

  // ===========================================================================
  //  이름 태그 (Ctrl + 클릭)
  // ===========================================================================
  function stripTags(name) { return String(name).replace(/\s*(\(#[^()]*\))+\s*$/, ''); }

  // 이름을 바꾼 뒤에도 이름으로 가리키던 익스프레션이 여전히 이 레이어를 가리키는지 확인
  function nameRefsStillValid(entry, ctx, del) {
    var fresh = { C: ctx.C, comps: ctx.comps, names: {} }, i, j, rec, refs, ok, hasRef, text;
    for (i = 0; i < ctx.exprs.length; i++) {
      rec = ctx.exprs[i];
      if (rec.key === entry.key || del[rec.key] === true) continue;
      hasRef = false;
      for (j = 0; j < rec.refs.length; j++) {
        if (rec.refs[j].k === 'name' && rec.refs[j].idx === entry.index) hasRef = true;
      }
      if (!hasRef) continue;
      try { text = rec.prop.expression; } catch (e) { return false; }
      refs = parseExpressionRefs(text, rec.user, rec.comp, fresh);
      ok = false;
      for (j = 0; j < refs.length; j++) {
        if (refs[j].k === 'name' && refs[j].idx === entry.layer.index) ok = true;
      }
      if (!ok) return false;
    }
    return true;
  }

  function applyTags(entry, ctx, del) {
    var ly = entry.layer, oldName = ly.name, base = stripTags(oldName), tags = '', newName, wasLocked = false, ok = true, i;
    for (i = 0; i < entry.tags.length; i++) tags += '(#' + entry.tags[i] + ')';
    if (!tags) return true;
    newName = base ? base + ' ' + tags : tags;
    if (newName === oldName) return true;
    try {
      wasLocked = ly.locked;
      if (wasLocked) ly.locked = false;
      ly.name = newName;
      if (!nameRefsStillValid(entry, ctx, del)) {
        ly.name = oldName; // AE 가 익스프레션 속 이름을 따라 고치지 못한 경우 되돌림
        ok = false;
      }
    } catch (e) {
      ok = false;
    } finally {
      if (wasLocked) {
        try { ly.locked = true; } catch (e) {}
      }
    }
    return ok;
  }

  // ===========================================================================
  //  실행
  // ===========================================================================
  function allLayers(comp) {
    var out = [], i;
    for (i = 1; i <= comp.numLayers; i++) out.push(comp.layer(i));
    return out;
  }

  // 컴포지션과, 그 안에 프리컴프로 들어 있는 컴포지션을 끝까지 (위에서 아래 순서로)
  function collectCompTree(root) {
    var list = [root], seen = {}, i, j, ly, src;
    seen['k' + root.id] = true;
    for (i = 0; i < list.length; i++) {
      for (j = 1; j <= list[i].numLayers; j++) {
        ly = list[i].layer(j);
        if (!(ly instanceof AVLayer)) continue;
        try { src = ly.source; } catch (e) { src = null; }
        if (src instanceof CompItem && !seen['k' + src.id]) {
          seen['k' + src.id] = true;
          list.push(src);
        }
      }
    }
    return list;
  }

  // 컴포지션 하나에서 layers 를 검사하고, 지워도 되는 것만 지웁니다.
  function processComp(C, layers, raw, quick) {
    var selected = {}, entries = [], del = {}, doomed = [], byIdx = {}, lists = [raw.exprs, raw.layerProps];
    var res, ctx, changed, e, i, j, r, is, tagSeen;
    for (i = 0; i < layers.length; i++) selected[layerKey(layers[i])] = true;
    ctx = contextFor(C, raw);
    for (i = 0; i < layers.length; i++) {
      e = { layer: layers[i], key: layerKey(layers[i]), name: layers[i].name, index: layers[i].index };
      e.issues = analyzeLayer(layers[i], ctx, selected, quick);
      entries.push(e);
      del[e.key] = true;
    }

    // 함께 지우는 레이어끼리의 연결은 괜찮습니다. 남겨야 할 레이어가 생기면
    // 그 레이어를 쓰던 레이어도 다시 확인해야 하므로 더 바뀌지 않을 때까지 반복합니다.
    do {
      changed = false;
      for (i = 0; i < entries.length; i++) {
        e = entries[i];
        if (del[e.key] !== true) continue;
        for (j = 0; j < e.issues.length; j++) {
          if (!isWaived(e.issues[j], del)) {
            del[e.key] = false;
            changed = true;
            break;
          }
        }
      }
    } while (changed);

    res = { comp: C, compName: C.name, deleted: [], kept: [], waived: false, ctx: ctx, del: del };
    for (i = 0; i < entries.length; i++) {
      if (del[entries[i].key] !== true) continue;
      entries[i].raws = [];
      byIdx['i' + entries[i].index] = entries[i];
      doomed.push(entries[i]);
    }
    // 지울 레이어의 익스프레션 · 레이어 선택 항목은 목록에서 뺍니다 (지운 뒤에는 읽을 수 없음)
    for (i = 0; i < lists.length; i++) {
      for (j = 0; j < lists[i].length; j++) {
        r = lists[i][j];
        if (!r.dead && r.comp.id === C.id && byIdx['i' + r.user.index]) byIdx['i' + r.user.index].raws.push(r);
      }
    }
    doomed.sort(function (a, b) { return b.index - a.index; }); // 아래 레이어부터
    for (i = 0; i < doomed.length; i++) {
      try {
        doomed[i].layer.remove();
        for (j = 0; j < doomed[i].raws.length; j++) doomed[i].raws[j].dead = true;
      } catch (err) {
        doomed[i].error = String(err);
        del[doomed[i].key] = false;
      }
    }

    for (i = 0; i < entries.length; i++) {
      e = entries[i];
      if (del[e.key] === true) {
        res.deleted.push('"' + e.name + '"');
        if (e.issues.length) res.waived = true;
        continue;
      }
      e.reasons = [];
      e.tags = [];
      e.live = false;
      tagSeen = {};
      if (e.error) e.reasons.push('[오류] 삭제하지 못했습니다: ' + e.error);
      for (j = 0; j < e.issues.length; j++) {
        is = e.issues[j];
        if (isWaived(is, del)) continue;
        if (is.tag === 'Visible' || is.tag === 'Audio') e.live = true;
        e.reasons.push('[' + is.cat + '] ' + issueText(is, del));
        if (!tagSeen[is.tag]) {
          tagSeen[is.tag] = true;
          e.tags.push(is.tag);
        }
      }
      e.label = label(e.layer);
      res.kept.push(e);
    }
    return res;
  }

  // mode: 'selection' 선택한 레이어 / 'comp' 지금 컴포지션 전체 / 'deep' 프리컴프 속까지
  function safeDelete(C, mode, layers, tagMode) {
    var comps = mode === 'deep' ? collectCompTree(C) : [C];
    var raw = scanProject(comps), results = {}, out, pass = 0, again, i, j, k, r, prev, kept;
    do {
      again = false;
      for (i = 0; i < comps.length; i++) {
        r = processComp(comps[i], mode === 'selection' ? layers : allLayers(comps[i]), raw, mode !== 'selection');
        if (r.deleted.length) again = true;
        k = 'k' + comps[i].id;
        prev = results[k];
        if (prev) {
          r.deleted = prev.deleted.concat(r.deleted);
          r.waived = r.waived || prev.waived;
        }
        results[k] = r;
      }
      pass++;
      // 한 컴포지션에서 지운 레이어 때문에 다른 컴포지션의 레이어가 풀려날 수 있으므로 다시 한 번
    } while (mode === 'deep' && again && pass < 20);

    out = { mode: mode, root: C.name, comps: [], tagMode: tagMode, tagged: 0, tagFailed: [] };
    for (i = 0; i < comps.length; i++) out.comps.push(results['k' + comps[i].id]);
    if (tagMode) {
      for (i = 0; i < out.comps.length; i++) {
        kept = out.comps[i].kept;
        for (j = 0; j < kept.length; j++) {
          // 한꺼번에 정리할 때는 보이거나 소리 나는 레이어 이름은 그대로 둡니다.
          if (mode !== 'selection' && kept[j].live) continue;
          if (!kept[j].tags.length) continue;
          if (applyTags(kept[j], out.comps[i].ctx, out.comps[i].del)) out.tagged++;
          else out.tagFailed.push(kept[j].label);
        }
      }
    }
    return out;
  }

  function showReport(headLines, bodyLines) {
    var w = new Window('dialog', TITLE), i, et, btns, ok;
    w.orientation = 'column';
    w.alignChildren = ['fill', 'top'];
    w.margins = 16;
    w.spacing = 8;
    for (i = 0; i < headLines.length; i++) w.add('statictext', undefined, headLines[i]);
    if (bodyLines.length) {
      et = w.add('edittext', undefined, bodyLines.join(NL), { multiline: true, scrolling: true, readonly: true });
      et.preferredSize = [600, Math.min(380, Math.max(120, bodyLines.length * 18 + 24))];
    }
    btns = w.add('group');
    btns.alignment = ['right', 'bottom'];
    ok = btns.add('button', undefined, '확인', { name: 'ok' });
    ok.onClick = function () { w.close(1); };
    w.defaultElement = ok;
    w.show();
  }

  function tagNotes(res, head, body) {
    if (!res.tagMode) return;
    if (res.tagged) head.push('지우지 않은 레이어 이름 끝에 이유 태그를 붙였습니다.');
    if (res.tagFailed.length) {
      body.push('');
      body.push('※ 이름을 바꾸면 익스프레션 연결이 끊어질 수 있어 태그를 붙이지 않은 레이어: ' + res.tagFailed.join(', '));
    }
  }

  function showSelectionResult(res) {
    var r = res.comps[0], total = r.deleted.length + r.kept.length, head = [], body = [], i, j, k;
    if (total === 1 && r.deleted.length === 1) return; // 한 개를 지웠으면 조용히 끝
    if (total === 1) {
      k = r.kept[0];
      head.push('레이어를 삭제하지 않았습니다.');
      body.push(k.label + ' — 지우면 아래와 같은 영향이 있습니다.');
      body.push('');
      for (j = 0; j < k.reasons.length; j++) body.push('• ' + k.reasons[j]);
    } else {
      head.push('선택한 레이어 ' + total + '개 중 ' + r.deleted.length + '개를 삭제했고, ' + r.kept.length + '개는 삭제하지 않았습니다.');
      body.push('■ 삭제함 (' + r.deleted.length + ')');
      for (i = 0; i < r.deleted.length; i++) body.push('    - ' + r.deleted[i]);
      if (!r.deleted.length) body.push('    (없음)');
      body.push('');
      body.push('■ 삭제하지 않음 (' + r.kept.length + ')');
      for (i = 0; i < r.kept.length; i++) {
        body.push('    - ' + r.kept[i].label);
        for (j = 0; j < r.kept[i].reasons.length; j++) body.push('        • ' + r.kept[i].reasons[j]);
      }
      if (!r.kept.length) body.push('    (없음)');
      if (r.waived) {
        body.push('');
        body.push('※ 함께 선택해서 같이 지운 레이어끼리의 연결(부모, 트랙 매트, 익스프레션 등)은 문제로 보지 않았습니다.');
      }
    }
    tagNotes(res, head, body);
    showReport(head, body);
  }

  // 컴포지션 전체 / 프리컴프 속까지 정리한 결과: 컴포지션마다 묶어서 보여 줍니다.
  function showCompResult(res) {
    var head = [], body = [], del = 0, kept = 0, waived = false, i, j, m, r, live;
    for (i = 0; i < res.comps.length; i++) {
      del += res.comps[i].deleted.length;
      kept += res.comps[i].kept.length;
      if (res.comps[i].waived) waived = true;
    }
    head.push(res.mode === 'deep' ?
      '"' + res.root + '" 컴포지션과 그 안의 프리컴프 ' + (res.comps.length - 1) + '개까지 모든 레이어를 검사했습니다.' :
      '"' + res.root + '" 컴포지션의 모든 레이어를 검사했습니다.');
    head.push('레이어 ' + (del + kept) + '개 중 ' + del + '개를 삭제했고, ' + kept + '개는 삭제하지 않았습니다.');
    for (i = 0; i < res.comps.length; i++) {
      r = res.comps[i];
      live = 0;
      for (j = 0; j < r.kept.length; j++) if (r.kept[j].live) live++;
      if (i) body.push('');
      body.push('[컴포지션] "' + r.compName + '" — 삭제 ' + r.deleted.length + '개 · 남김 ' + r.kept.length + '개');
      if (r.deleted.length) {
        body.push('    ■ 삭제함 (' + r.deleted.length + ')');
        for (j = 0; j < r.deleted.length; j++) body.push('        - ' + r.deleted[j]);
      }
      if (r.kept.length) {
        body.push('    ■ 삭제하지 않음 (' + r.kept.length + ')');
        if (live) body.push('        - 화면에 보이거나 소리가 나는 레이어 ' + live + '개');
        for (j = 0; j < r.kept.length; j++) {
          if (r.kept[j].live) continue;
          body.push('        - ' + r.kept[j].label);
          for (m = 0; m < r.kept[j].reasons.length; m++) body.push('            • ' + r.kept[j].reasons[m]);
        }
      }
    }
    if (waived) {
      body.push('');
      body.push('※ 같이 지운 레이어끼리의 연결(부모, 트랙 매트, 익스프레션 등)은 문제로 보지 않았습니다.');
    }
    tagNotes(res, head, body);
    showReport(head, body);
  }

  function run(mods) {
    var C = app.project.activeItem, sel, layers = [], mode, i, res = null;
    if (!(C instanceof CompItem)) {
      alert('컴포지션 타임라인을 열고 눌러 주세요.', TITLE);
      return;
    }
    sel = C.selectedLayers;
    if (sel && sel.length) {
      mode = 'selection';
      for (i = 0; i < sel.length; i++) layers.push(sel[i]);
      layers.sort(function (a, b) { return a.index - b.index; });
    } else {
      mode = mods.deep ? 'deep' : 'comp';
      if (!C.numLayers) {
        alert('"' + C.name + '" 컴포지션에 레이어가 없습니다.', TITLE);
        return;
      }
    }
    app.beginUndoGroup(SCRIPT_NAME);
    try {
      res = safeDelete(C, mode, layers, mods.tag);
    } catch (err) {
      alert('스크립트 실행 중 오류가 발생했습니다.\n' + err + (err.line ? ' (line ' + err.line + ')' : ''), TITLE);
    } finally {
      app.endUndoGroup();
    }
    if (!res) return;
    if (mode === 'selection') showSelectionResult(res);
    else showCompResult(res);
  }

  function buildUI(host) {
    var win = (host instanceof Panel) ? host : new Window('palette', TITLE, undefined, { resizeable: true });
    var btn;
    win.orientation = 'column';
    win.alignChildren = ['fill', 'top'];
    win.margins = 8;
    win.spacing = 6;
    btn = win.add('button', undefined, 'Safe Delete');
    btn.helpTip = '선택한 레이어가 다른 곳에 쓰이는지 검사한 뒤, 지워도 영향이 없는 레이어만 삭제합니다.\n' +
      '아무것도 선택하지 않으면 지금 컴포지션의 모든 레이어를 정리합니다.\n' +
      'Shift + 클릭 (선택 없음): 안에 든 프리컴프까지 끝까지 정리\n' +
      'Ctrl(Mac: Cmd) + 클릭: 지우지 않은 레이어 이름에 이유 태그 붙이기 (Shift 와 함께 써도 됨)';
    btn.onClick = function () {
      var ks = ScriptUI.environment.keyboardState;
      run({ tag: !!(ks && (ks.ctrlKey || ks.metaKey)), deep: !!(ks && ks.shiftKey) });
    };
    win.onResizing = win.onResize = function () { this.layout.resize(); };
    if (win instanceof Window) {
      win.center();
      win.show();
    } else {
      win.layout.layout(true);
    }
    return win;
  }

  buildUI(thisObj);
})(this);
