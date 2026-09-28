//@target illustrator
//@targetengine 'AlignPlus'
/*
 * ============================================================================
 *  Align+ 정렬 플러스  (AlignPlus.jsx)  v1.0.0
 * ============================================================================
 *  정렬 패널에 없는 기능을 모은 패널입니다. 창을 띄워 둔 채로
 *  객체를 선택하고 버튼만 누르면 됩니다. (정렬 패널처럼 계속 열려 있음)
 *
 *  1) 간격 같게 배열 (가로 / 세로)
 *     - 크기가 서로 다른 객체도 객체 사이의 '빈 간격'이 모두 같아지도록 배열
 *     - 자동: 양 끝 객체는 그대로 두고 사이 간격만 똑같이
 *     - 직접 입력: 간격을 5 mm 처럼 정확히 지정 (처음/가운데/끝 기준)
 *     - 클리핑 마스크는 보이는 모양 기준, 선 두께 포함 여부 선택
 *
 *  2) 단락 정렬 - 위치 유지
 *     - 포인트 텍스트의 정렬(왼쪽/가운데/오른쪽)을 바꿔도 글자가 제자리에 있음
 *     - 영역 텍스트는 틀 안에서 정렬 (양쪽 정렬 포함)
 *     - 그룹 안의 텍스트, 글자를 편집 중인 텍스트에도 적용
 *
 *  실행 : 파일 > 스크립트 > 기타 스크립트... 에서 이 파일 선택 (패널이 열림)
 *  지원 : Adobe Illustrator CC 2017 이상 (Windows / macOS)
 *  주의 : 이 파일은 'UTF-8 (BOM)' 인코딩으로 저장해야 한글이 깨지지 않습니다.
 *
 *  구조 : 패널(팔레트) 창은 문서를 직접 고치지 못하므로, 버튼을 누르면
 *         alignPlusCore() 함수의 코드를 BridgeTalk 으로 일러스트레이터에 보내 실행합니다.
 *         그래서 alignPlusCore() 는 바깥 변수를 쓰지 않고, 영어(ASCII)로만 작성합니다.
 * ============================================================================
 */
(function () {
  // UTF-8(BOM)로 읽히지 않으면 한글 문구가 모두 깨지므로, 안내만 하고 끝냅니다.
  if ('가'.length !== 1 || '가'.charCodeAt(0) !== 0xAC00) {
    alert('This script file was saved with the wrong text encoding.\n' +
      'Download the .jsx file again (do not copy & paste the code) or save it as "UTF-8 with BOM".\n\n' +
      '\uC2A4\uD06C\uB9BD\uD2B8 \uD30C\uC77C\uC758 \uC778\uCF54\uB529\uC774 \uC62C\uBC14\uB974\uC9C0 \uC54A\uC544 \uD55C\uAE00\uC774 \uAE68\uC84C\uC2B5\uB2C8\uB2E4.\n' +
      '\uCF54\uB4DC\uB97C \uBCF5\uC0AC\uD574 \uBD99\uC5EC\uB123\uC9C0 \uB9D0\uACE0 .jsx \uD30C\uC77C\uC744 \uADF8\uB300\uB85C \uB0B4\uB824\uBC1B\uAC70\uB098,\n' +
      '\uD3B8\uC9D1\uAE30\uC5D0\uC11C "UTF-8 (BOM)" \uD615\uC2DD\uC73C\uB85C \uB2E4\uC2DC \uC800\uC7A5\uD574 \uC8FC\uC138\uC694.');
    return;
  }

  var SCRIPT_TITLE = 'Align+ 정렬 플러스';
  var SETTINGS_NAME = 'AlignPlus';
  var PANEL_KEY = 'AlignPlusPanel'; // 이미 열린 패널을 찾기 위한 이름

  // points: 1 단위가 몇 pt 인지 (스크립트 안에서는 모든 길이를 pt 로 계산합니다)
  var UNITS = [
    { label: 'mm', points: 72 / 25.4 },
    { label: 'cm', points: 72 / 2.54 },
    { label: 'pt', points: 1 },
    { label: 'px', points: 1 },
    { label: 'in', points: 72 }
  ];
  var ANCHORS = ['처음 객체 고정', '가운데 고정', '끝 객체 고정'];
  var ANCHOR_KEYS = ['start', 'center', 'end'];
  var JUSTIFY_NAMES = {
    LEFT: '왼쪽 정렬',
    CENTER: '가운데 정렬',
    RIGHT: '오른쪽 정렬',
    FULLJUSTIFYLASTLINELEFT: '양쪽 정렬',
    FULLJUSTIFY: '강제 양쪽 정렬'
  };

  // 처음 실행할 때의 기본값. 이후에는 마지막으로 쓴 값을 기억합니다.
  var DEFAULTS = {
    gapMode: 'auto',
    gap: '5',
    unit: 'mm',
    anchor: 0,
    useVisibleBounds: true,
    windowX: -1,
    windowY: -1
  };

  // 이미 열려 있으면 새로 만들지 않고 앞으로 가져옵니다.
  var existing = $.global[PANEL_KEY];
  if (existing) {
    try {
      existing.show();
      existing.active = true;
      return;
    } catch (e) {
      $.global[PANEL_KEY] = null; // 닫힌 창이 남아 있던 경우 새로 만듭니다.
    }
  }

  try {
    buildPanel(loadSettings(SETTINGS_NAME, DEFAULTS));
  } catch (e) {
    alert('패널을 여는 중 오류가 발생했습니다.\n\n' + e.message + (e.line ? '\n(줄 ' + e.line + ')' : ''), SCRIPT_TITLE, true);
  }

  // ==========================================================================
  //  패널 (팔레트 창)
  // ==========================================================================
  function buildPanel(s) {
    var unitIndex = unitIndexOf(s.unit);

    var win = new Window('palette', SCRIPT_TITLE, undefined, { closeButton: true });
    win.orientation = 'column';
    win.alignChildren = ['fill', 'top'];
    win.spacing = 8;
    win.margins = 12;

    // ---- 1) 간격 같게 배열 -------------------------------------------------
    var pGap = addPanel(win, '간격 같게 배열');
    var gGapButtons = addRow(pGap);
    var btnHorizontal = gGapButtons.add('button', undefined, '가로 간격 같게');
    var btnVertical = gGapButtons.add('button', undefined, '세로 간격 같게');
    btnHorizontal.preferredSize.width = 128;
    btnVertical.preferredSize.width = 128;
    btnHorizontal.helpTip = '왼쪽 → 오른쪽 순서로, 객체 사이의 빈 간격을 모두 같게 만듭니다.';
    btnVertical.helpTip = '위 → 아래 순서로, 객체 사이의 빈 간격을 모두 같게 만듭니다.';

    var gMode = addRow(pGap);
    var rbAuto = gMode.add('radiobutton', undefined, '자동 (양 끝 고정)');
    var rbFixed = gMode.add('radiobutton', undefined, '직접 입력');
    rbAuto.helpTip = '맨 앞과 맨 끝 객체는 그대로 두고, 사이 간격만 똑같이 나눕니다. (3개 이상)';
    rbFixed.helpTip = '입력한 간격으로 붙여 놓습니다. (2개 이상)';
    rbFixed.value = (s.gapMode === 'fixed');
    rbAuto.value = !rbFixed.value;

    var gValue = addRow(pGap);
    addLabel(gValue, '간격:', 40);
    var etGap = gValue.add('edittext', undefined, s.gap);
    etGap.characters = 6;
    var ddUnit = gValue.add('dropdownlist', undefined, unitLabels());
    ddUnit.selection = unitIndex;

    var gAnchor = addRow(pGap);
    addLabel(gAnchor, '기준:', 40);
    var ddAnchor = gAnchor.add('dropdownlist', undefined, ANCHORS);
    ddAnchor.selection = clampIndex(s.anchor, ANCHORS.length);
    ddAnchor.helpTip = '직접 입력한 간격으로 배열할 때 어느 쪽을 제자리에 둘지 고릅니다.';

    var cbVisible = pGap.add('checkbox', undefined, '선 두께까지 포함한 크기로 계산');
    cbVisible.value = s.useVisibleBounds;

    // ---- 2) 단락 정렬 - 위치 유지 -----------------------------------------
    var pText = addPanel(win, '단락 정렬 (위치 유지)');
    var gJustify = addRow(pText);
    var btnLeft = gJustify.add('button', undefined, '왼쪽');
    var btnCenter = gJustify.add('button', undefined, '가운데');
    var btnRight = gJustify.add('button', undefined, '오른쪽');
    var gJustify2 = addRow(pText);
    var btnJustify = gJustify2.add('button', undefined, '양쪽 정렬');
    var btnJustifyAll = gJustify2.add('button', undefined, '강제 양쪽');
    var justifyButtons = [btnLeft, btnCenter, btnRight, btnJustify, btnJustifyAll];
    for (var i = 0; i < justifyButtons.length; i++) justifyButtons[i].preferredSize.width = 84;
    btnLeft.helpTip = '왼쪽 정렬로 바꾸고, 글자는 제자리에 둡니다.';
    btnCenter.helpTip = '가운데 정렬로 바꾸고, 글자는 제자리에 둡니다.';
    btnRight.helpTip = '오른쪽 정렬로 바꾸고, 글자는 제자리에 둡니다.';
    btnJustify.helpTip = '양쪽 정렬(마지막 줄 왼쪽). 영역 텍스트에만 적용됩니다.';
    btnJustifyAll.helpTip = '모든 줄 양쪽 정렬. 영역 텍스트에만 적용됩니다.';
    pText.add('statictext', undefined, '양쪽 정렬은 영역 텍스트에만 적용됩니다.');

    // ---- 상태 표시 ---------------------------------------------------------
    var stStatus = win.add('statictext', undefined, '객체나 텍스트를 선택하고 버튼을 누르세요.', { multiline: true });
    stStatus.preferredSize = [270, 34]; // 두 줄까지 표시

    // ---- 동작 연결 ---------------------------------------------------------
    btnHorizontal.onClick = function () { distribute('h'); };
    btnVertical.onClick = function () { distribute('v'); };
    btnLeft.onClick = function () { justify('LEFT'); };
    btnCenter.onClick = function () { justify('CENTER'); };
    btnRight.onClick = function () { justify('RIGHT'); };
    btnJustify.onClick = function () { justify('FULLJUSTIFYLASTLINELEFT'); };
    btnJustifyAll.onClick = function () { justify('FULLJUSTIFY'); };
    rbAuto.onClick = function () { updateEnabled(); remember(); };
    rbFixed.onClick = function () { updateEnabled(); remember(); };
    cbVisible.onClick = remember;
    ddAnchor.onChange = remember;
    etGap.onChange = remember;
    var lastUnit = unitIndex;
    ddUnit.onChange = function () {
      // 단위를 바꾸면 입력해 둔 간격 값도 새 단위로 환산합니다.
      if (!ddUnit.selection || ddUnit.selection.index === lastUnit) return;
      var next = ddUnit.selection.index;
      etGap.text = convertText(etGap.text, UNITS[lastUnit], UNITS[next]);
      lastUnit = next;
      remember();
    };

    win.onClose = function () {
      remember();
      $.global[PANEL_KEY] = null;
      return true;
    };

    updateEnabled();
    placeWindow(win, s.windowX, s.windowY);
    $.global[PANEL_KEY] = win;
    win.show();

    // ---- 내부 함수 ---------------------------------------------------------
    function updateEnabled() {
      gValue.enabled = rbFixed.value;
      gAnchor.enabled = rbFixed.value;
    }

    function distribute(axis) {
      var fixed = rbFixed.value;
      var gap = parseNumber(etGap.text);
      if (fixed && isNaN(gap)) {
        setStatus('간격은 숫자로 입력해 주세요.');
        return;
      }
      remember();
      send({
        action: 'distribute',
        axis: axis,
        mode: fixed ? 'fixed' : 'auto',
        gap: fixed ? gap * UNITS[lastUnit].points : 0,
        anchor: ANCHOR_KEYS[ddAnchor.selection ? ddAnchor.selection.index : 0],
        visible: cbVisible.value
      });
    }

    function justify(name) {
      send({ action: 'justify', justification: name });
    }

    // alignPlusCore() 의 코드와 요청 값을 문자열로 만들어 일러스트레이터에 보냅니다.
    function send(request) {
      try {
        var bt = new BridgeTalk();
        bt.target = BridgeTalk.appSpecifier || 'illustrator';
        bt.body = '(' + alignPlusCore.toString() + ')(' + serialize(request) + ');';
        bt.onResult = function (result) {
          setStatus(describeResult(request, String(result.body)));
        };
        bt.onError = function (error) {
          setStatus('오류: ' + String(error.body));
        };
        setStatus('처리 중...');
        bt.send();
      } catch (e) {
        setStatus('오류: ' + e.message);
      }
    }

    // 결과 코드 → 한글 안내 문구
    function describeResult(request, body) {
      var p = body.split('|');
      if (p[0] === 'err') {
        if (p[1] === 'nodoc') return '열린 문서가 없습니다.';
        if (p[1] === 'textedit') return '텍스트 편집 중입니다. Esc 로 편집을 끝낸 뒤 다시 누르세요.';
        if (p[1] === 'few') return '객체를 ' + p[2] + '개 이상 선택하세요.';
        if (p[1] === 'notext') return '텍스트를 선택하세요. (그룹 안의 텍스트도 됩니다)';
        if (p[1] === 'exception') return '오류: ' + safeDecode(p[2]);
        return '알 수 없는 결과: ' + body;
      }
      if (p[1] === 'dist') {
        var unit = UNITS[lastUnit];
        var gapText = formatNumber(parseFloat(p[3]) / unit.points) + ' ' + unit.label;
        var what = request.axis === 'h' ? '가로' : '세로';
        return what + ' ' + p[2] + '개를 간격 ' + gapText + '로 배열했습니다.';
      }
      if (p[1] === 'just') {
        var point = parseInt(p[2], 10);
        var area = parseInt(p[3], 10);
        var path = parseInt(p[4], 10);
        var skipped = parseInt(p[5], 10);
        var failed = parseInt(p[6], 10);
        var parts = [];
        if (point) parts.push('포인트 ' + point + '개(제자리 유지)');
        if (area) parts.push('영역 ' + area + '개');
        if (path) parts.push('패스 ' + path + '개(위치 유지 안 됨)');
        var message = JUSTIFY_NAMES[request.justification] + ': ' + (parts.length ? parts.join(', ') : '바뀐 텍스트 없음');
        if (skipped) message += ' / 포인트 텍스트 ' + skipped + '개는 양쪽 정렬을 쓸 수 없어 건너뜀';
        if (failed) message += ' / ' + failed + '개 실패';
        return message;
      }
      return body;
    }

    function setStatus(text) {
      stStatus.text = text;
      stStatus.helpTip = text; // 글이 길어 잘려도 마우스를 올리면 전체가 보입니다.
    }

    function remember() {
      var location = [-1, -1];
      try {
        location = [win.location[0], win.location[1]];
      } catch (e) { /* 창 위치를 못 읽으면 저장하지 않음 */ }
      saveSettings(SETTINGS_NAME, {
        gapMode: rbFixed.value ? 'fixed' : 'auto',
        gap: etGap.text,
        unit: UNITS[lastUnit].label,
        anchor: ddAnchor.selection ? ddAnchor.selection.index : 0,
        useVisibleBounds: cbVisible.value,
        windowX: location[0],
        windowY: location[1]
      });
    }
  }

  // 마지막 위치에 창을 띄웁니다. 그 위치가 지금 화면 밖이면(모니터 변경 등) 가운데에 띄웁니다.
  function placeWindow(win, x, y) {
    if (x >= 0 && y >= 0) {
      try {
        for (var i = 0; i < $.screens.length; i++) {
          var sc = $.screens[i];
          if (x >= sc.left && x < sc.right - 40 && y >= sc.top && y < sc.bottom - 40) {
            win.location = [x, y];
            return;
          }
        }
      } catch (e) { /* 화면 정보를 못 읽으면 가운데로 */ }
    }
    win.center();
  }

  // ==========================================================================
  //  실제 작업 (일러스트레이터 안에서 실행됨)
  //  BridgeTalk 으로 코드째 보내므로: 바깥 변수 사용 금지, ASCII(영어)로만 작성.
  //  결과는 'ok|...' 또는 'err|...' 문자열로 돌려주고, 패널이 한글 문구로 바꿔 보여 줍니다.
  // ==========================================================================
  function alignPlusCore(req) {
    try {
      if (app.documents.length === 0) return 'err|nodoc';
      var sel = app.activeDocument.selection;
      if (req.action === 'distribute') return distribute(sel, req);
      if (req.action === 'justify') return justify(sel, req);
      return 'err|exception|' + encodeURIComponent('unknown action ' + req.action);
    } catch (e) {
      return 'err|exception|' + encodeURIComponent(String(e.message || e));
    }

    // ---- Equal gaps -------------------------------------------------------
    // Travel coordinate t: x for horizontal, -y for vertical (so t grows to the right / downwards).
    function distribute(sel, o) {
      if (sel && sel.typename === 'TextRange') return 'err|textedit';
      var items = [];
      var i;
      for (i = 0; sel && i < sel.length; i++) items.push(measure(sel[i], i, o.visible));
      var minimum = o.mode === 'fixed' ? 2 : 3;
      if (items.length < minimum) return 'err|few|' + minimum;

      var horizontal = o.axis === 'h';
      items.sort(function (a, b) {
        var d = horizontal ? a.cx - b.cx : b.cy - a.cy;
        if (Math.abs(d) > 1e-6) return d;
        d = horizontal ? b.cy - a.cy : a.cx - b.cx;
        return Math.abs(d) > 1e-6 ? d : a.index - b.index;
      });

      var start = Infinity;
      var end = -Infinity;
      var total = 0;
      for (i = 0; i < items.length; i++) {
        var it = items[i];
        it.lead = horizontal ? it.b[0] : -it.b[1];
        it.size = (horizontal ? it.b[2] : -it.b[3]) - it.lead;
        if (it.lead < start) start = it.lead;
        if (it.lead + it.size > end) end = it.lead + it.size;
        total += it.size;
      }

      var gap;
      var pos = start;
      if (o.mode === 'fixed') {
        gap = o.gap;
        var length = total + gap * (items.length - 1);
        if (o.anchor === 'end') pos = end - length;
        else if (o.anchor === 'center') pos = (start + end - length) / 2;
      } else {
        gap = (end - start - total) / (items.length - 1);
      }

      var patterns = preference('transformPatterns', true);
      for (i = 0; i < items.length; i++) {
        var delta = pos - items[i].lead;
        if (Math.abs(delta) > 1e-6) {
          if (horizontal) items[i].ref.translate(delta, 0, true, patterns, true, patterns);
          else items[i].ref.translate(0, -delta, true, patterns, true, patterns);
        }
        pos += items[i].size + gap;
      }
      return 'ok|dist|' + items.length + '|' + gap;
    }

    function measure(item, index, visible) {
      var target = item;
      if (item.typename === 'GroupItem' && item.clipped) {
        // clipping groups: use the mask shape, not the hidden artwork
        for (var k = 0; k < item.pageItems.length; k++) {
          var child = item.pageItems[k];
          if ((child.typename === 'PathItem' && child.clipping) ||
            (child.typename === 'CompoundPathItem' && child.pathItems.length && child.pathItems[0].clipping)) {
            target = child;
            break;
          }
        }
      }
      var r = visible ? target.visibleBounds : target.geometricBounds;
      var b = [r[0], r[1], r[2], r[3]];
      return { ref: item, index: index, b: b, cx: (b[0] + b[2]) / 2, cy: (b[1] + b[3]) / 2 };
    }

    // ---- Justification without moving point text ---------------------------
    function justify(sel, o) {
      var name = o.justification;
      var value = Justification[name];
      var fullJustify = name.indexOf('FULLJUSTIFY') === 0;
      var frames = [];
      var range = null;
      var i;
      if (sel && sel.typename === 'TextRange') {
        // editing text: change the selected paragraphs (or the whole story for a bare cursor)
        range = sel.length > 0 ? sel : sel.story.textRange;
        for (i = 0; i < sel.story.textFrames.length; i++) frames.push(sel.story.textFrames[i]);
      } else {
        for (i = 0; sel && i < sel.length; i++) collectText(sel[i], frames);
      }
      if (!frames.length) return 'err|notext';

      var count = { point: 0, area: 0, path: 0, skipped: 0, failed: 0 };
      var before = [];
      var todo = [];
      for (i = 0; i < frames.length; i++) {
        var kind = frames[i].kind;
        if (kind == TextType.POINTTEXT && fullJustify) {
          count.skipped++;
          continue;
        }
        todo.push(frames[i]);
        before.push(kind == TextType.POINTTEXT ? frames[i].geometricBounds : null);
      }

      if (range) {
        setJustification(range, value);
      }
      for (i = 0; i < todo.length; i++) {
        var frame = todo[i];
        try {
          if (!range) setJustification(frame.textRange, value);
          if (!before[i]) {
            if (frame.kind == TextType.PATHTEXT) count.path++;
            else count.area++;
            continue;
          }
          // point text: move it back so the text stays where it was
          var vertical = frame.orientation == TextOrientation.VERTICAL;
          var p0 = referencePoint(before[i], name, vertical);
          var p1 = referencePoint(frame.geometricBounds, name, vertical);
          var dx = p0[0] - p1[0];
          var dy = p0[1] - p1[1];
          if (Math.abs(dx) > 1e-6 || Math.abs(dy) > 1e-6) frame.translate(dx, dy, true, true, true, true);
          count.point++;
        } catch (e) {
          count.failed++;
        }
      }
      return 'ok|just|' + count.point + '|' + count.area + '|' + count.path + '|' + count.skipped + '|' + count.failed;
    }

    // The side named by the new justification stays fixed: left edge for LEFT, right edge for RIGHT,
    // centre for CENTER (top / bottom / middle for vertical text). The other axis keeps its centre.
    function referencePoint(b, name, vertical) {
      var t = name === 'LEFT' ? 0 : (name === 'RIGHT' ? 1 : 0.5);
      if (vertical) return [(b[0] + b[2]) / 2, b[1] - (b[1] - b[3]) * t];
      return [b[0] + (b[2] - b[0]) * t, (b[1] + b[3]) / 2];
    }

    function setJustification(range, value) {
      try {
        range.paragraphAttributes.justification = value;
        return;
      } catch (e) { /* fall back to one paragraph at a time */ }
      var paragraphs = range.paragraphs;
      for (var k = 0; k < paragraphs.length; k++) {
        try {
          if (paragraphs[k].length > 0) paragraphs[k].paragraphAttributes.justification = value;
        } catch (e2) { /* empty or locked paragraph */ }
      }
    }

    function collectText(item, out) {
      if (item.typename === 'TextFrame') {
        out.push(item);
      } else if (item.typename === 'GroupItem') {
        for (var k = 0; k < item.pageItems.length; k++) collectText(item.pageItems[k], out);
      }
    }

    function preference(key, fallback) {
      try {
        return app.preferences.getBooleanPreference(key);
      } catch (e) {
        return fallback;
      }
    }
  }

  // ==========================================================================
  //  작은 도우미 함수
  // ==========================================================================
  // 요청 값을 코드 문자열로 바꿉니다. 한글 등은 \uXXXX 로 적어 ASCII 만 보냅니다.
  function serialize(obj) {
    var parts = [];
    for (var key in obj) {
      if (!obj.hasOwnProperty(key)) continue;
      var v = obj[key];
      if (typeof v === 'number') parts.push(key + ':' + (isFinite(v) ? String(v) : '0'));
      else if (typeof v === 'boolean') parts.push(key + ':' + (v ? 'true' : 'false'));
      else parts.push(key + ':' + quote(String(v)));
    }
    return '{' + parts.join(',') + '}';
  }

  function quote(text) {
    var out = "'";
    for (var i = 0; i < text.length; i++) {
      var c = text.charAt(i);
      var code = text.charCodeAt(i);
      if (c === '\\' || c === "'") out += '\\' + c;
      else if (code < 32 || code > 126) out += '\\u' + ('000' + code.toString(16)).slice(-4);
      else out += c;
    }
    return out + "'";
  }

  function safeDecode(text) {
    try {
      return decodeURIComponent(text || '');
    } catch (e) {
      return String(text);
    }
  }

  function unitLabels() {
    var labels = [];
    for (var i = 0; i < UNITS.length; i++) labels.push(UNITS[i].label);
    return labels;
  }

  function unitIndexOf(label) {
    for (var i = 0; i < UNITS.length; i++) {
      if (UNITS[i].label === label) return i;
    }
    return 0;
  }

  function convertText(text, fromUnit, toUnit) {
    var v = parseNumber(text);
    if (isNaN(v)) return text;
    return formatNumber(v * fromUnit.points / toUnit.points);
  }

  function formatNumber(v) {
    return String(Math.round(v * 1000) / 1000);
  }

  // '5', '2.5', '2,5'(쉼표 소수점), '-3' 을 숫자로 읽습니다. 숫자가 아니면 NaN
  function parseNumber(text) {
    var t = String(text).replace(/^\s+|\s+$/g, '').replace(',', '.');
    return /^[+-]?(\d+\.?\d*|\.\d+)$/.test(t) ? parseFloat(t) : NaN;
  }

  function clampIndex(value, length) {
    var n = parseInt(value, 10);
    return (n >= 0 && n < length) ? n : 0;
  }

  // ---- 화면 구성 도우미 ------------------------------------------------------
  function addPanel(parent, title) {
    var panel = parent.add('panel', undefined, title);
    panel.orientation = 'column';
    panel.alignChildren = ['left', 'top'];
    panel.spacing = 6;
    panel.margins = [10, 16, 10, 10];
    return panel;
  }

  function addRow(parent) {
    var group = parent.add('group');
    group.orientation = 'row';
    group.alignChildren = ['left', 'center'];
    group.spacing = 6;
    return group;
  }

  function addLabel(parent, text, width) {
    var label = parent.add('statictext', undefined, text);
    if (width) label.preferredSize.width = width;
    return label;
  }

  // ---- 설정 저장/불러오기 (사용자 폴더/IllustratorUIScripts/이름.ini) ----------
  function settingsFile(name) {
    var folder = new Folder(Folder.userData.fullName + '/IllustratorUIScripts');
    if (!folder.exists) folder.create();
    return new File(folder.fullName + '/' + name + '.ini');
  }

  function loadSettings(name, defaults) {
    var result = {};
    var key;
    for (key in defaults) {
      if (defaults.hasOwnProperty(key)) result[key] = defaults[key];
    }
    try {
      var file = settingsFile(name);
      if (!file.exists) return result;
      file.encoding = 'UTF-8';
      if (!file.open('r')) return result;
      var lines = file.read().split(/\r\n|\r|\n/);
      file.close();
      for (var i = 0; i < lines.length; i++) {
        var eq = lines[i].indexOf('=');
        if (eq < 1) continue;
        key = lines[i].substring(0, eq);
        if (!defaults.hasOwnProperty(key)) continue;
        try {
          var raw = decodeURIComponent(lines[i].substring(eq + 1));
          var type = typeof defaults[key];
          if (type === 'boolean') result[key] = (raw === 'true');
          else if (type === 'number') result[key] = isNaN(parseFloat(raw)) ? defaults[key] : parseFloat(raw);
          else result[key] = raw;
        } catch (e) { /* 이 줄은 건너뜀 */ }
      }
    } catch (e) { /* 설정 파일을 못 읽으면 기본값 사용 */ }
    return result;
  }

  function saveSettings(name, values) {
    try {
      var lines = [];
      for (var key in values) {
        if (values.hasOwnProperty(key)) lines.push(key + '=' + encodeURIComponent(String(values[key])));
      }
      var file = settingsFile(name);
      file.encoding = 'UTF-8';
      if (file.open('w')) {
        file.write(lines.join('\n'));
        file.close();
      }
    } catch (e) { /* 설정 저장 실패는 무시 */ }
  }
})();
