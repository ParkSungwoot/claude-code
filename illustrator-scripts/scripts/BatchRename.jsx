//@target illustrator
/*
 * ============================================================================
 *  일괄 이름 변경 · 번호 매기기  (BatchRename.jsx)  v1.0.0
 * ============================================================================
 *  대지 · 레이어 · 선택한 객체의 이름, 또는 선택한 텍스트의 내용을
 *  규칙에 따라 한꺼번에 바꿉니다. 창에서 결과를 미리 확인한 뒤 적용합니다.
 *
 *  - 새 이름 짓기(패턴) : 'Page_{nn}'  ->  Page_01, Page_02, ...
 *  - 찾아서 바꾸기      : 이름의 일부만 바꾸기 (정규식 사용 가능)
 *  - 순서               : 기본 순서 / 화면 위치(가로 방향, 세로 방향) / 역순
 *
 *  패턴 기호
 *    {n}     번호 1, 2, 3 ...     {nn}  01, 02 ...     {nnn}  001, 002 ...
 *    {name}  원래 이름 (텍스트가 대상이면 원래 내용)
 *
 *  실행 : 파일 > 스크립트 > 기타 스크립트... 에서 이 파일 선택
 *  지원 : Adobe Illustrator CS6 이상 (Windows / macOS)
 *  주의 : 이 파일은 'UTF-8 (BOM)' 인코딩으로 저장해야 한글이 깨지지 않습니다.
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

  var SCRIPT_TITLE = '일괄 이름 변경 · 번호 매기기';
  var SETTINGS_NAME = 'BatchRename';
  var PREVIEW_LIMIT = 200; // 미리보기 목록에 보여 줄 최대 줄 수
  var LABEL_WIDTH = 72;    // 입력 칸 앞 라벨 너비(px)

  var TARGETS = [
    { key: 'artboards', label: '대지' },
    { key: 'layers', label: '레이어' },
    { key: 'objects', label: '선택 객체' },
    { key: 'texts', label: '선택 텍스트' }
  ];

  var ORDER_HINTS = {
    artboards: '기본 순서: 대지 패널 순서',
    layers: '레이어 패널의 위 → 아래 순서 (위치 정렬은 쓸 수 없음)',
    objects: '기본 순서: 선택 목록 순서 (보통 레이어 패널의 위 → 아래)',
    texts: '기본 순서: 선택 목록 순서 (보통 레이어 패널의 위 → 아래)'
  };

  var SORT_MODES = [
    '기본 순서',
    '가로 방향 (위 행부터, 왼쪽 → 오른쪽)',
    '세로 방향 (왼쪽 열부터, 위 → 아래)'
  ];

  var TYPE_LABELS = {
    PathItem: '패스',
    CompoundPathItem: '컴파운드 패스',
    GroupItem: '그룹',
    TextFrame: '텍스트',
    PlacedItem: '연결 이미지',
    RasterItem: '이미지',
    SymbolItem: '심볼',
    MeshItem: '메시',
    PluginItem: '플러그인 객체',
    GraphItem: '그래프',
    LegacyTextItem: '레거시 텍스트',
    NonNativeItem: '기타 객체'
  };

  // 처음 실행할 때의 기본값. 이후에는 마지막으로 쓴 값을 기억합니다.
  var DEFAULTS = {
    target: 'artboards',
    includeSublayers: false,
    sortMode: 0,
    reverse: false,
    mode: 'pattern',
    patternArtboards: 'Page_{nn}',
    patternLayers: 'Layer_{nn}',
    patternObjects: 'Item_{nn}',
    patternTexts: '{nnn}',
    start: '1',
    step: '1',
    findText: '',
    replaceText: '',
    caseSensitive: false,
    useRegex: false
  };

  try {
    main();
  } catch (e) {
    alert('스크립트 실행 중 오류가 발생했습니다.\n\n' + e.message + (e.line ? '\n(줄 ' + e.line + ')' : ''), SCRIPT_TITLE, true);
  }

  // ==========================================================================
  //  진입점
  // ==========================================================================
  function main() {
    if (app.documents.length === 0) {
      alert('열려 있는 문서가 없습니다.\n문서를 연 뒤 다시 실행해 주세요.', SCRIPT_TITLE);
      return;
    }
    var doc = app.activeDocument;
    var plan = showDialog(doc, loadSettings(SETTINGS_NAME, DEFAULTS));
    if (!plan) return; // 취소

    var changed = 0;
    var failed = [];
    for (var i = 0; i < plan.entries.length; i++) {
      if (plan.names[i] === plan.entries[i].name) continue;
      try {
        plan.entries[i].apply(plan.names[i]);
        changed++;
      } catch (e) {
        failed.push(plan.entries[i].display + ' : ' + e.message);
      }
    }
    if (failed.length) {
      alert(changed + '개를 바꿨지만 ' + failed.length + '개는 바꾸지 못했습니다.\n\n' +
        failed.slice(0, 5).join('\n') + (failed.length > 5 ? '\n...' : ''), SCRIPT_TITLE, true);
    }
  }

  // ==========================================================================
  //  대화상자
  // ==========================================================================
  function showDialog(doc, s) {
    var sel = readSelection(doc);
    var counts = {
      artboards: doc.artboards.length,
      layers: doc.layers.length,
      objects: sel.items.length,
      texts: countTextFrames(sel.items)
    };
    // 대상마다 패턴을 따로 기억합니다.
    var patterns = {
      artboards: s.patternArtboards,
      layers: s.patternLayers,
      objects: s.patternObjects,
      texts: s.patternTexts
    };
    var state = { target: s.target, entries: [], plan: null };
    if (!counts[state.target]) state.target = 'artboards';

    var win = new Window('dialog', SCRIPT_TITLE);
    win.orientation = 'column';
    win.alignChildren = ['fill', 'top'];
    win.spacing = 10;
    win.margins = 16;

    // ---- 대상 -------------------------------------------------------------
    var pTarget = addPanel(win, '대상');
    var gTarget = addRow(pTarget);
    var rbTarget = {};
    var i;
    for (i = 0; i < TARGETS.length; i++) {
      var t = TARGETS[i];
      rbTarget[t.key] = gTarget.add('radiobutton', undefined, t.label + ' (' + counts[t.key] + ')');
      rbTarget[t.key].enabled = counts[t.key] > 0;
    }
    rbTarget[state.target].value = true;
    var cbSublayers = pTarget.add('checkbox', undefined, '하위 레이어도 포함');
    cbSublayers.value = s.includeSublayers;
    if (sel.textEditing) {
      pTarget.add('statictext', undefined, '※ 텍스트 편집 중이라 선택 대상을 쓸 수 없습니다. (Esc로 편집을 끝낸 뒤 다시 실행)');
    }

    // ---- 순서 -------------------------------------------------------------
    var pOrder = addPanel(win, '순서');
    var gOrder = addRow(pOrder);
    addLabel(gOrder, '정렬:', LABEL_WIDTH);
    var ddSort = gOrder.add('dropdownlist', undefined, SORT_MODES);
    ddSort.selection = clampIndex(s.sortMode, SORT_MODES.length);
    var cbReverse = gOrder.add('checkbox', undefined, '역순');
    cbReverse.value = s.reverse;
    var stOrderHint = pOrder.add('statictext', undefined, '');
    stOrderHint.preferredSize.width = 440;

    // ---- 이름 규칙 --------------------------------------------------------
    var pRule = addPanel(win, '이름 규칙');
    var gMode = addRow(pRule);
    var rbPattern = gMode.add('radiobutton', undefined, '새 이름 짓기 (패턴)');
    var rbReplace = gMode.add('radiobutton', undefined, '찾아서 바꾸기');
    rbPattern.value = (s.mode !== 'replace');
    rbReplace.value = (s.mode === 'replace');

    var gPattern = addRow(pRule);
    addLabel(gPattern, '패턴:', LABEL_WIDTH);
    var etPattern = gPattern.add('edittext', undefined, patterns[state.target]);
    etPattern.characters = 30;

    var gFind = addRow(pRule);
    addLabel(gFind, '찾기:', LABEL_WIDTH);
    var etFind = gFind.add('edittext', undefined, s.findText);
    etFind.characters = 30;

    var gReplace = addRow(pRule);
    addLabel(gReplace, '바꾸기:', LABEL_WIDTH);
    var etReplace = gReplace.add('edittext', undefined, s.replaceText);
    etReplace.characters = 30;

    var gFindOptions = addRow(pRule);
    addLabel(gFindOptions, '', LABEL_WIDTH);
    var cbCase = gFindOptions.add('checkbox', undefined, '대소문자 구분');
    cbCase.value = s.caseSensitive;
    var cbRegex = gFindOptions.add('checkbox', undefined, '정규식 사용');
    cbRegex.value = s.useRegex;

    var gNumber = addRow(pRule);
    addLabel(gNumber, '시작 번호:', LABEL_WIDTH);
    var etStart = gNumber.add('edittext', undefined, s.start);
    etStart.characters = 6;
    gNumber.add('statictext', undefined, '증가:');
    var etStep = gNumber.add('edittext', undefined, s.step);
    etStep.characters = 6;

    var gHelp = pRule.add('group');
    gHelp.orientation = 'column';
    gHelp.alignChildren = ['left', 'top'];
    gHelp.spacing = 2;
    gHelp.add('statictext', undefined, '기호:  {n} 번호   {nn} 01   {nnn} 001   {name} 원래 이름(내용)');
    gHelp.add('statictext', undefined, '"바꾸기" 칸에도 같은 기호를 쓸 수 있고, 정규식이면 $1, $2 도 쓸 수 있습니다.');

    // ---- 미리보기 ----------------------------------------------------------
    var pPreview = addPanel(win, '미리보기');
    pPreview.alignChildren = ['fill', 'top'];
    var lbPreview = pPreview.add('listbox', undefined, []);
    lbPreview.preferredSize = [460, 170];
    var stStatus = pPreview.add('statictext', undefined, '');
    stStatus.preferredSize.width = 460;

    var buttons = addButtons(win, '적용');

    // ---- 동작 연결 ---------------------------------------------------------
    for (i = 0; i < TARGETS.length; i++) {
      rbTarget[TARGETS[i].key].onClick = makeTargetHandler(TARGETS[i].key);
    }
    cbSublayers.onClick = function () {
      reloadEntries();
      refresh();
    };
    rbPattern.onClick = rbReplace.onClick = function () {
      updateEnabled();
      refresh();
    };
    ddSort.onChange = refresh;
    cbReverse.onClick = refresh;
    cbCase.onClick = refresh;
    cbRegex.onClick = refresh;
    etPattern.onChanging = refresh;
    etFind.onChanging = refresh;
    etReplace.onChanging = refresh;
    etStart.onChanging = refresh;
    etStep.onChanging = refresh;

    buttons.ok.onClick = function () {
      refresh(); // 마지막 입력까지 반영
      if (!state.plan) return;
      patterns[state.target] = etPattern.text;
      saveSettings(SETTINGS_NAME, {
        target: state.target,
        includeSublayers: cbSublayers.value,
        sortMode: ddSort.selection ? ddSort.selection.index : 0,
        reverse: cbReverse.value,
        mode: rbReplace.value ? 'replace' : 'pattern',
        patternArtboards: patterns.artboards,
        patternLayers: patterns.layers,
        patternObjects: patterns.objects,
        patternTexts: patterns.texts,
        start: etStart.text,
        step: etStep.text,
        findText: etFind.text,
        replaceText: etReplace.text,
        caseSensitive: cbCase.value,
        useRegex: cbRegex.value
      });
      win.close(1);
    };
    buttons.cancel.onClick = function () {
      win.close(2);
    };

    win.onShow = function () {
      (rbPattern.value ? etPattern : etFind).active = true;
    };

    reloadEntries();
    updateEnabled();
    refresh();

    win.center();
    return win.show() === 1 ? state.plan : null;

    // ---- 내부 함수 ---------------------------------------------------------
    function makeTargetHandler(key) {
      return function () {
        patterns[state.target] = etPattern.text;
        state.target = key;
        etPattern.text = patterns[key];
        reloadEntries();
        updateEnabled();
        refresh();
      };
    }

    function reloadEntries() {
      state.entries = collectEntries(doc, state.target, cbSublayers.value, sel.items);
    }

    function updateEnabled() {
      var isPattern = rbPattern.value;
      gPattern.enabled = isPattern;
      gFind.enabled = !isPattern;
      gReplace.enabled = !isPattern;
      gFindOptions.enabled = !isPattern;
      cbSublayers.enabled = (state.target === 'layers');
      ddSort.enabled = (state.target !== 'layers');
      stOrderHint.text = ORDER_HINTS[state.target];
    }

    function readOptions() {
      var o = {
        target: state.target,
        mode: rbReplace.value ? 'replace' : 'pattern',
        pattern: etPattern.text,
        findText: etFind.text,
        replaceText: etReplace.text,
        caseSensitive: cbCase.value,
        useRegex: cbRegex.value,
        sortMode: (state.target !== 'layers' && ddSort.selection) ? ddSort.selection.index : 0,
        reverse: cbReverse.value,
        start: parseInteger(etStart.text),
        step: parseInteger(etStep.text),
        error: ''
      };
      if (isNaN(o.start) || isNaN(o.step)) o.error = '시작 번호와 증가 값은 정수로 입력해 주세요.';
      return o;
    }

    function refresh() {
      var o = readOptions();
      var ordered = orderEntries(state.entries, o.sortMode, o.reverse);
      var result = o.error ? { error: o.error } : buildNames(ordered, o);

      state.plan = null;
      lbPreview.removeAll();
      var limit = Math.min(ordered.length, PREVIEW_LIMIT);
      for (var k = 0; k < limit; k++) {
        var line = ordered[k].display;
        if (result.names) line += '   →   ' + displayText(result.names[k], '(빈 이름)');
        lbPreview.add('item', line);
      }
      if (ordered.length > limit) lbPreview.add('item', '... 외 ' + (ordered.length - limit) + '개');

      if (!ordered.length) return setStatus('바꿀 항목이 없습니다.', false);
      if (result.error) return setStatus('확인 필요: ' + result.error, false);

      state.plan = { entries: ordered, names: result.names };
      var message = '총 ' + ordered.length + '개 중 ' + result.changed + '개가 바뀝니다.';
      if (result.allSame && ordered.length > 1) message += '  (모두 같은 이름이 됩니다)';
      setStatus(message, result.changed > 0);
    }

    function setStatus(text, canApply) {
      stStatus.text = text;
      buttons.ok.enabled = canApply;
    }
  }

  // ==========================================================================
  //  이름 만들기 · 정렬
  // ==========================================================================
  function buildNames(entries, o) {
    var re = null;
    if (o.mode === 'replace') {
      if (o.findText === '') return { error: '찾을 내용을 입력해 주세요.' };
      try {
        re = new RegExp(o.useRegex ? o.findText : escapeRegExp(o.findText), o.caseSensitive ? 'g' : 'gi');
      } catch (e) {
        return { error: '정규식이 올바르지 않습니다. (' + e.message + ')' };
      }
    } else if (o.pattern === '') {
      return { error: '패턴을 입력해 주세요.' };
    }

    var names = [];
    var changed = 0;
    var allSame = true;
    var emptyAt = -1;
    for (var k = 0; k < entries.length; k++) {
      var num = o.start + k * o.step;
      var oldName = entries[k].name;
      var newName;
      if (re) {
        var replacement = expandTokens(o.replaceText, num, oldName, o.useRegex);
        // 정규식이 아니면 바꿀 글자를 그대로 넣습니다($ 기호도 글자 그대로).
        newName = o.useRegex ? oldName.replace(re, replacement) : oldName.replace(re, constant(replacement));
      } else {
        newName = expandTokens(o.pattern, num, oldName, false);
      }
      names.push(newName);
      if (newName !== oldName) changed++;
      if (newName !== names[0]) allSame = false;
      if (newName === '' && emptyAt < 0) emptyAt = k;
    }

    var result = { names: names, changed: changed, allSame: allSame };
    // 객체 이름은 비워도 되지만(이름 없음), 대지·레이어·텍스트는 비울 수 없습니다.
    if (emptyAt >= 0 && o.target !== 'objects') result.error = (emptyAt + 1) + '번째 항목이 빈 이름이 됩니다.';
    return result;
  }

  // {n}, {nn}, {nnn}... 과 {name} 을 실제 값으로 바꿉니다.
  function expandTokens(template, num, name, escapeDollar) {
    return template.replace(/\{(n+|name)\}/g, function (all, key) {
      if (key === 'name') return escapeDollar ? name.replace(/\$/g, '$$$$') : name;
      return padNumber(num, key.length);
    });
  }

  function orderEntries(entries, sortMode, reverse) {
    var list = entries.slice(0);
    if (sortMode === 1 || sortMode === 2) list = sortByPosition(list, sortMode === 2);
    if (reverse) list.reverse();
    return list;
  }

  // 화면 위치로 정렬합니다. 비슷한 높이(또는 가로 위치)에 있는 것끼리 한 줄로 묶은 뒤,
  // 줄 안에서 왼쪽 → 오른쪽(또는 위 → 아래) 순서로 놓습니다.
  // 일러스트레이터 스크립트 좌표는 위로 갈수록 y 값이 커집니다. bounds = [왼, 위, 오른, 아래]
  function sortByPosition(entries, byColumns) {
    var items = [];
    var i;
    for (i = 0; i < entries.length; i++) {
      var b = entries[i].bounds;
      if (!b) return entries;
      items.push({
        entry: entries[i],
        order: i,
        cx: (b[0] + b[2]) / 2,
        cy: (b[1] + b[3]) / 2,
        w: Math.abs(b[2] - b[0]),
        h: Math.abs(b[1] - b[3])
      });
    }

    var mainAxis = byColumns ? function (a, b) { return a.cx - b.cx; } : function (a, b) { return b.cy - a.cy; };
    var subAxis = byColumns ? function (a, b) { return b.cy - a.cy; } : function (a, b) { return a.cx - b.cx; };
    items.sort(function (a, b) { return mainAxis(a, b) || a.order - b.order; });

    // 같은 줄로 볼 거리: 객체 크기 중앙값의 절반
    var tolerance = median(items, byColumns ? 'w' : 'h') / 2;
    var lines = [];
    var line = null;
    var lineStart = 0;
    for (i = 0; i < items.length; i++) {
      var pos = byColumns ? items[i].cx : items[i].cy;
      if (line && Math.abs(pos - lineStart) <= tolerance) {
        line.push(items[i]);
      } else {
        line = [items[i]];
        lines.push(line);
        lineStart = pos;
      }
    }

    var out = [];
    for (i = 0; i < lines.length; i++) {
      lines[i].sort(function (a, b) { return subAxis(a, b) || a.order - b.order; });
      for (var j = 0; j < lines[i].length; j++) out.push(lines[i][j].entry);
    }
    return out;
  }

  function median(items, key) {
    if (!items.length) return 0;
    var values = [];
    for (var i = 0; i < items.length; i++) values.push(items[i][key]);
    values.sort(function (a, b) { return a - b; });
    return values[Math.floor(values.length / 2)];
  }

  // ==========================================================================
  //  대상 모으기
  // ==========================================================================
  function collectEntries(doc, target, includeSublayers, selectedItems) {
    var list = [];
    var i;
    if (target === 'artboards') {
      for (i = 0; i < doc.artboards.length; i++) list.push(artboardEntry(doc.artboards[i]));
    } else if (target === 'layers') {
      addLayerEntries(doc.layers, 0, includeSublayers, list);
    } else {
      for (i = 0; i < selectedItems.length; i++) {
        var item = selectedItems[i];
        if (target === 'objects') list.push(objectEntry(item));
        else if (item.typename === 'TextFrame') list.push(textEntry(item));
      }
    }
    return list;
  }

  // 각 항목: name = 원래 이름, display = 미리보기에 보일 글자, bounds = 위치, apply = 실제로 바꾸는 함수
  function artboardEntry(artboard) {
    return {
      name: artboard.name,
      display: artboard.name,
      bounds: artboard.artboardRect,
      apply: function (value) { artboard.name = value; }
    };
  }

  function addLayerEntries(layers, depth, recursive, list) {
    for (var i = 0; i < layers.length; i++) {
      list.push(layerEntry(layers[i], depth));
      if (recursive && layers[i].layers.length) addLayerEntries(layers[i].layers, depth + 1, true, list);
    }
  }

  function layerEntry(layer, depth) {
    return {
      name: layer.name,
      display: repeatText('     ', depth) + layer.name,
      bounds: null,
      apply: function (value) { layer.name = value; }
    };
  }

  function objectEntry(item) {
    var name = item.name;
    return {
      name: name,
      display: name !== '' ? name : '<' + (TYPE_LABELS[item.typename] || item.typename) + '>',
      bounds: readBounds(item),
      apply: function (value) { item.name = value; }
    };
  }

  function textEntry(frame) {
    var contents = frame.contents;
    return {
      name: contents,
      display: displayText(contents, '(빈 텍스트)'),
      bounds: readBounds(frame),
      apply: function (value) { frame.contents = value; }
    };
  }

  // 선택 상태를 읽습니다. 텍스트를 편집 중이면(커서가 글자 안에 있으면) 객체 목록 대신 TextRange 가 돌아옵니다.
  function readSelection(doc) {
    var result = { items: [], textEditing: false };
    var sel;
    try {
      sel = doc.selection;
    } catch (e) {
      return result;
    }
    if (!sel) return result;
    if (sel.typename === 'TextRange') {
      result.textEditing = true;
      return result;
    }
    for (var i = 0; i < sel.length; i++) result.items.push(sel[i]);
    return result;
  }

  function countTextFrames(items) {
    var n = 0;
    for (var i = 0; i < items.length; i++) {
      if (items[i].typename === 'TextFrame') n++;
    }
    return n;
  }

  function readBounds(item) {
    try {
      return item.geometricBounds;
    } catch (e) {
      return null;
    }
  }

  // ==========================================================================
  //  작은 도우미 함수
  // ==========================================================================
  function displayText(text, emptyLabel) {
    var s = String(text).replace(/[\r\n\u0003]+/g, ' ¶ ');
    if (s === '') return emptyLabel;
    return s.length > 40 ? s.substring(0, 39) + '...' : s;
  }

  function constant(value) {
    return function () { return value; };
  }

  function escapeRegExp(text) {
    return text.replace(/[.*+?^${}()|[\]\\\/-]/g, '\\$&');
  }

  function padNumber(num, width) {
    var s = String(Math.abs(num));
    while (s.length < width) s = '0' + s;
    return (num < 0 ? '-' : '') + s;
  }

  function parseInteger(text) {
    var t = trim(text);
    return /^[+-]?\d+$/.test(t) ? parseInt(t, 10) : NaN;
  }

  function trim(text) {
    return String(text).replace(/^\s+|\s+$/g, '');
  }

  function repeatText(text, count) {
    var s = '';
    for (var i = 0; i < count; i++) s += text;
    return s;
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
    panel.spacing = 8;
    panel.margins = [12, 16, 12, 12];
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

  // 확인/취소 버튼. Windows 는 [확인][취소], macOS 는 [취소][확인] 순서가 자연스럽습니다.
  function addButtons(win, okText) {
    var group = win.add('group');
    group.orientation = 'row';
    group.alignment = ['right', 'top'];
    var ok, cancel;
    if (File.fs === 'Windows') {
      ok = group.add('button', undefined, okText, { name: 'ok' });
      cancel = group.add('button', undefined, '취소', { name: 'cancel' });
    } else {
      cancel = group.add('button', undefined, '취소', { name: 'cancel' });
      ok = group.add('button', undefined, okText, { name: 'ok' });
    }
    return { ok: ok, cancel: cancel };
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
