//@target illustrator
/*
 * ============================================================================
 *  격자 정렬  (GridArrange.jsx)  v1.0.0
 * ============================================================================
 *  선택한 객체들을 원하는 열 수와 간격으로 바둑판처럼 배치합니다.
 *  '미리보기'를 켜면 값을 바꿀 때마다 문서에 바로 반영되고,
 *  '취소'를 누르면 원래 위치로 돌아갑니다.
 *
 *  - 열 수, 채우는 방향(가로/세로), 가로·세로 간격(mm, cm, pt, px, in)
 *  - 칸 크기: 가장 큰 객체 기준(균일) 또는 행·열마다 맞춤(촘촘하게)
 *  - 칸 안 정렬: 왼쪽/가운데/오른쪽, 위/가운데/아래
 *  - 순서: 현재 위치(가로/세로 방향), 선택 목록 순서, 이름 순서, 역순
 *  - 클리핑 마스크는 가려진 부분을 빼고 보이는 모양 기준으로 배치
 *
 *  실행 : 객체를 2개 이상 선택 → 파일 > 스크립트 > 기타 스크립트... 에서 이 파일 선택
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

  var SCRIPT_TITLE = '격자 정렬';
  var SETTINGS_NAME = 'GridArrange';
  var LABEL_WIDTH = 76;

  // points: 1 단위가 몇 pt 인지 (스크립트 안에서는 모든 길이를 pt 로 계산합니다)
  var UNITS = [
    { label: 'mm', points: 72 / 25.4 },
    { label: 'cm', points: 72 / 2.54 },
    { label: 'pt', points: 1 },
    { label: 'px', points: 1 },
    { label: 'in', points: 72 }
  ];
  var DIRECTIONS = ['가로 방향 (한 행씩 채움)', '세로 방향 (한 열씩 채움)'];
  var CELL_MODES = ['가장 큰 객체 기준 (모든 칸 같은 크기)', '행 · 열마다 맞춤 (촘촘하게)'];
  var ALIGN_H = ['왼쪽', '가운데', '오른쪽'];
  var ALIGN_V = ['위', '가운데', '아래'];
  var ORDERS = ['현재 위치 (가로 방향)', '현재 위치 (세로 방향)', '선택 목록 순서', '이름 순서'];

  // 처음 실행할 때의 기본값. 이후에는 마지막으로 쓴 값을 기억합니다.
  var DEFAULTS = {
    columns: '',          // 비어 있으면 객체 수에 맞춰 자동(√개수)
    direction: 0,
    gapX: '5',
    gapY: '5',
    unit: '',             // 비어 있으면 문서의 눈금자 단위
    cellMode: 0,
    alignH: 1,
    alignV: 1,
    order: 0,
    reverse: false,
    useVisibleBounds: true,
    preview: true
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
    var sel = doc.selection;
    if (sel && sel.typename === 'TextRange') {
      alert('텍스트를 편집하는 중입니다.\nEsc 키로 편집을 끝내고 객체를 선택한 뒤 다시 실행해 주세요.', SCRIPT_TITLE);
      return;
    }
    if (!sel || sel.length < 2) {
      alert('정렬할 객체를 2개 이상 선택해 주세요.', SCRIPT_TITLE);
      return;
    }

    var moveOptions = {
      patterns: readPreference('transformPatterns', true) // 환경설정의 '패턴 변형'을 따릅니다.
    };
    var items = [];
    for (var i = 0; i < sel.length; i++) items.push(wrapItem(sel[i], i));

    var defaults = copyObject(DEFAULTS);
    defaults.useVisibleBounds = readPreference('includeStrokeInBounds', true);
    var options = showDialog(doc, items, loadSettings(SETTINGS_NAME, defaults), moveOptions);

    // 미리보기로 옮겨 둔 것은 먼저 원래 자리로 돌려놓습니다.
    // 그래야 적용 후 실행 취소(Ctrl/Cmd+Z) 한 번으로 원래 배치로 돌아갈 수 있습니다.
    if (hasOffsets(items)) {
      restoreItems(items, moveOptions);
      app.redraw();
    }
    if (!options) return; // 취소

    var failed = applyLayout(computeLayout(items, options), options.useVisibleBounds, moveOptions);
    if (failed) alert(failed + '개 객체는 옮기지 못했습니다. (잠긴 객체인지 확인해 주세요)', SCRIPT_TITLE, true);
  }

  // ==========================================================================
  //  대화상자
  // ==========================================================================
  function showDialog(doc, items, s, moveOptions) {
    var unitIndex = unitIndexOf(s.unit !== '' ? s.unit : rulerUnitLabel(doc));
    var columnsText = s.columns !== '' ? s.columns : String(Math.ceil(Math.sqrt(items.length)));
    var chosen = null;

    var win = new Window('dialog', SCRIPT_TITLE + '  (객체 ' + items.length + '개)');
    win.orientation = 'column';
    win.alignChildren = ['fill', 'top'];
    win.spacing = 10;
    win.margins = 16;

    // ---- 배치 -------------------------------------------------------------
    var pLayout = addPanel(win, '배치');
    var gColumns = addRow(pLayout);
    addLabel(gColumns, '열 수:', LABEL_WIDTH);
    var etColumns = gColumns.add('edittext', undefined, columnsText);
    etColumns.characters = 5;
    var stGrid = gColumns.add('statictext', undefined, '');
    stGrid.preferredSize.width = 160;

    var gDirection = addRow(pLayout);
    addLabel(gDirection, '채우는 방향:', LABEL_WIDTH);
    var ddDirection = gDirection.add('dropdownlist', undefined, DIRECTIONS);
    ddDirection.selection = clampIndex(s.direction, DIRECTIONS.length);

    // ---- 간격 -------------------------------------------------------------
    var pGap = addPanel(win, '간격');
    var gGap = addRow(pGap);
    addLabel(gGap, '가로:', LABEL_WIDTH);
    var etGapX = gGap.add('edittext', undefined, s.gapX);
    etGapX.characters = 6;
    gGap.add('statictext', undefined, '세로:');
    var etGapY = gGap.add('edittext', undefined, s.gapY);
    etGapY.characters = 6;
    var ddUnit = gGap.add('dropdownlist', undefined, unitLabels());
    ddUnit.selection = unitIndex;

    // ---- 칸 ---------------------------------------------------------------
    var pCell = addPanel(win, '칸 크기와 정렬');
    var gCell = addRow(pCell);
    addLabel(gCell, '칸 크기:', LABEL_WIDTH);
    var ddCell = gCell.add('dropdownlist', undefined, CELL_MODES);
    ddCell.selection = clampIndex(s.cellMode, CELL_MODES.length);

    var gAlign = addRow(pCell);
    addLabel(gAlign, '가로 정렬:', LABEL_WIDTH);
    var ddAlignH = gAlign.add('dropdownlist', undefined, ALIGN_H);
    ddAlignH.selection = clampIndex(s.alignH, ALIGN_H.length);
    gAlign.add('statictext', undefined, '  세로 정렬:');
    var ddAlignV = gAlign.add('dropdownlist', undefined, ALIGN_V);
    ddAlignV.selection = clampIndex(s.alignV, ALIGN_V.length);

    // ---- 순서 -------------------------------------------------------------
    var pOrder = addPanel(win, '순서');
    var gOrder = addRow(pOrder);
    addLabel(gOrder, '순서:', LABEL_WIDTH);
    var ddOrder = gOrder.add('dropdownlist', undefined, ORDERS);
    ddOrder.selection = clampIndex(s.order, ORDERS.length);
    var cbReverse = gOrder.add('checkbox', undefined, '역순');
    cbReverse.value = s.reverse;

    // ---- 옵션 -------------------------------------------------------------
    var pOptions = addPanel(win, '옵션');
    var cbVisible = pOptions.add('checkbox', undefined, '선 두께까지 포함한 크기로 계산');
    cbVisible.value = s.useVisibleBounds;
    var cbPreview = pOptions.add('checkbox', undefined, '미리보기');
    cbPreview.value = s.preview;
    pOptions.add('statictext', undefined, '선택한 객체들이 차지한 영역의 왼쪽 위 모서리부터 배치합니다.');

    var stStatus = win.add('statictext', undefined, '');
    stStatus.preferredSize.width = 420;

    var buttons = addButtons(win, '정렬');

    // ---- 동작 연결 ---------------------------------------------------------
    var lastUnit = unitIndex;
    ddUnit.onChange = function () {
      // 단위를 바꾸면 입력해 둔 간격 값도 새 단위로 환산합니다.
      if (!ddUnit.selection || ddUnit.selection.index === lastUnit) return;
      var next = ddUnit.selection.index;
      etGapX.text = convertText(etGapX.text, UNITS[lastUnit], UNITS[next]);
      etGapY.text = convertText(etGapY.text, UNITS[lastUnit], UNITS[next]);
      lastUnit = next;
      update();
    };
    etColumns.onChanging = update;
    etGapX.onChanging = update;
    etGapY.onChanging = update;
    ddDirection.onChange = update;
    ddCell.onChange = update;
    ddAlignH.onChange = update;
    ddAlignV.onChange = update;
    ddOrder.onChange = update;
    cbReverse.onClick = update;
    cbVisible.onClick = update;
    cbPreview.onClick = function () {
      if (cbPreview.value) {
        update();
      } else {
        restoreItems(items, moveOptions);
        app.redraw();
      }
    };

    buttons.ok.onClick = function () {
      var o = readOptions();
      if (o.error) {
        stStatus.text = '확인 필요: ' + o.error;
        return;
      }
      chosen = o;
      saveSettings(SETTINGS_NAME, {
        columns: etColumns.text,
        direction: ddDirection.selection.index,
        gapX: etGapX.text,
        gapY: etGapY.text,
        unit: UNITS[lastUnit].label,
        cellMode: ddCell.selection.index,
        alignH: ddAlignH.selection.index,
        alignV: ddAlignV.selection.index,
        order: ddOrder.selection.index,
        reverse: cbReverse.value,
        useVisibleBounds: cbVisible.value,
        preview: cbPreview.value
      });
      win.close(1);
    };
    buttons.cancel.onClick = function () {
      win.close(2);
    };
    win.onShow = function () {
      etColumns.active = true;
    };

    update();
    win.center();
    return win.show() === 1 ? chosen : null;

    // ---- 내부 함수 ---------------------------------------------------------
    function readOptions() {
      var unit = UNITS[lastUnit];
      var columns = parseInteger(etColumns.text);
      var gapX = parseNumber(etGapX.text);
      var gapY = parseNumber(etGapY.text);
      var o = {
        columns: columns,
        direction: ddDirection.selection ? ddDirection.selection.index : 0,
        gapX: gapX * unit.points,
        gapY: gapY * unit.points,
        cellMode: ddCell.selection ? ddCell.selection.index : 0,
        alignH: ddAlignH.selection ? ddAlignH.selection.index : 1,
        alignV: ddAlignV.selection ? ddAlignV.selection.index : 1,
        order: ddOrder.selection ? ddOrder.selection.index : 0,
        reverse: cbReverse.value,
        useVisibleBounds: cbVisible.value,
        error: ''
      };
      if (isNaN(columns) || columns < 1 || columns > 1000) o.error = '열 수는 1~1000 사이의 정수로 입력해 주세요.';
      else if (isNaN(gapX) || isNaN(gapY)) o.error = '간격은 숫자로 입력해 주세요.';
      return o;
    }

    function update() {
      var o = readOptions();
      if (o.error) {
        stGrid.text = '';
        stStatus.text = '확인 필요: ' + o.error;
        buttons.ok.enabled = false;
        return;
      }
      var layout = computeLayout(items, o);
      stGrid.text = '→ ' + layout.columns + '열 × ' + layout.rows + '행';
      stStatus.text = '객체 ' + items.length + '개를 ' + layout.columns + '열 × ' + layout.rows + '행으로 배치합니다.';
      buttons.ok.enabled = true;
      if (cbPreview.value) {
        var failed = applyLayout(layout, o.useVisibleBounds, moveOptions);
        app.redraw();
        if (failed) stStatus.text += ' (' + failed + '개는 옮길 수 없음)';
      }
    }
  }

  // ==========================================================================
  //  배치 계산
  // ==========================================================================
  // 각 객체가 놓일 칸과 새 위치(왼쪽, 위)를 계산합니다. 문서는 건드리지 않습니다.
  // 일러스트레이터 스크립트 좌표는 위로 갈수록 y 값이 커집니다. bounds = [왼, 위, 오른, 아래]
  function computeLayout(items, o) {
    var list = orderItems(items, o);
    var n = list.length;
    var columns = Math.min(o.columns, n);
    var rows = Math.ceil(n / columns);
    if (o.direction === 1) columns = Math.ceil(n / rows); // 세로 방향: 행 수를 정한 뒤 열을 하나씩 채움

    var colWidth = [];
    var rowHeight = [];
    var r, c, i;
    for (c = 0; c < columns; c++) colWidth[c] = 0;
    for (r = 0; r < rows; r++) rowHeight[r] = 0;

    var cells = [];
    var maxWidth = 0;
    var maxHeight = 0;
    var originLeft = Infinity;
    var originTop = -Infinity;
    for (i = 0; i < n; i++) {
      if (o.direction === 1) {
        r = i % rows;
        c = Math.floor(i / rows);
      } else {
        r = Math.floor(i / columns);
        c = i % columns;
      }
      var b = boundsOf(list[i], o.useVisibleBounds);
      var w = b[2] - b[0];
      var h = b[1] - b[3];
      cells.push({ item: list[i], row: r, col: c, width: w, height: h });
      if (w > colWidth[c]) colWidth[c] = w;
      if (h > rowHeight[r]) rowHeight[r] = h;
      if (w > maxWidth) maxWidth = w;
      if (h > maxHeight) maxHeight = h;
      if (b[0] < originLeft) originLeft = b[0];
      if (b[1] > originTop) originTop = b[1];
    }
    if (o.cellMode === 0) {
      for (c = 0; c < columns; c++) colWidth[c] = maxWidth;
      for (r = 0; r < rows; r++) rowHeight[r] = maxHeight;
    }

    var colX = [0];
    var rowY = [0];
    for (c = 1; c < columns; c++) colX[c] = colX[c - 1] + colWidth[c - 1] + o.gapX;
    for (r = 1; r < rows; r++) rowY[r] = rowY[r - 1] + rowHeight[r - 1] + o.gapY;

    // 정렬 값 0/1/2 → 칸 안의 여백을 0 / 절반 / 전부 앞쪽에 둠
    for (i = 0; i < cells.length; i++) {
      var cell = cells[i];
      cell.left = originLeft + colX[cell.col] + (colWidth[cell.col] - cell.width) * o.alignH / 2;
      cell.top = originTop - rowY[cell.row] - (rowHeight[cell.row] - cell.height) * o.alignV / 2;
    }
    return { cells: cells, columns: columns, rows: rows };
  }

  function orderItems(items, o) {
    var list = items.slice(0);
    if (o.order === 0 || o.order === 1) {
      list = sortByPosition(list, o.order === 1, o.useVisibleBounds);
    } else if (o.order === 3) {
      list.sort(function (a, b) { return naturalCompare(a.name, b.name) || a.index - b.index; });
    }
    if (o.reverse) list.reverse();
    return list;
  }

  // 비슷한 높이(세로 방향이면 비슷한 가로 위치)에 있는 것끼리 한 줄로 묶은 뒤 줄 안에서 정렬합니다.
  function sortByPosition(items, byColumns, useVisible) {
    var points = [];
    var i;
    for (i = 0; i < items.length; i++) {
      var b = boundsOf(items[i], useVisible);
      points.push({
        item: items[i],
        cx: (b[0] + b[2]) / 2,
        cy: (b[1] + b[3]) / 2,
        size: byColumns ? b[2] - b[0] : b[1] - b[3]
      });
    }
    var mainAxis = byColumns ? function (a, b) { return a.cx - b.cx; } : function (a, b) { return b.cy - a.cy; };
    var subAxis = byColumns ? function (a, b) { return b.cy - a.cy; } : function (a, b) { return a.cx - b.cx; };
    points.sort(function (a, b) { return mainAxis(a, b) || a.item.index - b.item.index; });

    var sizes = [];
    for (i = 0; i < points.length; i++) sizes.push(points[i].size);
    sizes.sort(function (a, b) { return a - b; });
    var tolerance = sizes[Math.floor(sizes.length / 2)] / 2; // 크기 중앙값의 절반

    var lines = [];
    var line = null;
    var lineStart = 0;
    for (i = 0; i < points.length; i++) {
      var pos = byColumns ? points[i].cx : points[i].cy;
      if (line && Math.abs(pos - lineStart) <= tolerance) {
        line.push(points[i]);
      } else {
        line = [points[i]];
        lines.push(line);
        lineStart = pos;
      }
    }
    var out = [];
    for (i = 0; i < lines.length; i++) {
      lines[i].sort(function (a, b) { return subAxis(a, b) || a.item.index - b.item.index; });
      for (var j = 0; j < lines[i].length; j++) out.push(lines[i][j].item);
    }
    return out;
  }

  // 숫자는 숫자 크기대로 비교하는 이름 정렬 (Item2 < Item10)
  function naturalCompare(a, b) {
    var re = /(\d+|\D+)/g;
    var ax = String(a).toLowerCase().match(re) || [];
    var bx = String(b).toLowerCase().match(re) || [];
    for (var i = 0; i < ax.length && i < bx.length; i++) {
      var x = ax[i];
      var y = bx[i];
      if (x === y) continue;
      if (/^\d/.test(x) && /^\d/.test(y)) {
        var d = parseInt(x, 10) - parseInt(y, 10);
        if (d) return d;
        return x.length - y.length;
      }
      return x < y ? -1 : 1;
    }
    return ax.length - bx.length;
  }

  // ==========================================================================
  //  문서 적용 · 되돌리기
  // ==========================================================================
  // 원래 위치를 기준으로 목표 위치까지 옮깁니다. 이미 옮긴 거리(dx, dy)를 기억해 두므로
  // 미리보기 중 여러 번 호출해도, 되돌릴 때도 정확한 위치가 됩니다.
  function applyLayout(layout, useVisible, moveOptions) {
    var failed = 0;
    for (var i = 0; i < layout.cells.length; i++) {
      var cell = layout.cells[i];
      var it = cell.item;
      var b = boundsOf(it, useVisible);
      if (!moveTo(it, cell.left - b[0], cell.top - b[1], moveOptions)) failed++;
    }
    return failed;
  }

  function restoreItems(items, moveOptions) {
    for (var i = 0; i < items.length; i++) moveTo(items[i], 0, 0, moveOptions);
  }

  function moveTo(it, dx, dy, moveOptions) {
    var mx = dx - it.dx;
    var my = dy - it.dy;
    if (Math.abs(mx) < 1e-6 && Math.abs(my) < 1e-6) return true;
    try {
      // translate(가로, 세로, 객체, 칠 패턴, 칠 그레이디언트, 선 패턴)
      it.ref.translate(mx, my, true, moveOptions.patterns, true, moveOptions.patterns);
      it.dx = dx;
      it.dy = dy;
      return true;
    } catch (e) {
      return false;
    }
  }

  function hasOffsets(items) {
    for (var i = 0; i < items.length; i++) {
      if (items[i].dx !== 0 || items[i].dy !== 0) return true;
    }
    return false;
  }

  // 선택 객체를 감싸서 원래 경계(움직이기 전)와 지금까지 옮긴 거리를 함께 기억합니다.
  function wrapItem(pageItem, index) {
    return {
      ref: pageItem,
      index: index,
      name: itemName(pageItem),
      geometric: itemBounds(pageItem, false),
      visible: itemBounds(pageItem, true),
      dx: 0,
      dy: 0
    };
  }

  function boundsOf(it, useVisible) {
    return useVisible ? it.visible : it.geometric;
  }

  // 클리핑 마스크 그룹은 가려진 부분까지 경계에 들어가므로, 마스크 모양(클리핑 패스)의 경계를 씁니다.
  function itemBounds(item, visible) {
    var target = item;
    if (item.typename === 'GroupItem' && item.clipped) {
      var clip = findClippingPath(item);
      if (clip) target = clip;
    }
    var b = visible ? target.visibleBounds : target.geometricBounds;
    return [b[0], b[1], b[2], b[3]];
  }

  function findClippingPath(group) {
    for (var i = 0; i < group.pageItems.length; i++) {
      var child = group.pageItems[i];
      if (child.typename === 'PathItem' && child.clipping) return child;
      if (child.typename === 'CompoundPathItem' && child.pathItems.length && child.pathItems[0].clipping) return child;
    }
    return null;
  }

  function itemName(item) {
    if (item.name !== '') return item.name;
    return item.typename === 'TextFrame' ? item.contents : '';
  }

  // ==========================================================================
  //  단위 · 숫자 · 환경설정
  // ==========================================================================
  function rulerUnitLabel(doc) {
    var u;
    try {
      u = doc.rulerUnits;
    } catch (e) {
      return 'mm';
    }
    if (u == RulerUnits.Centimeters) return 'cm';
    if (u == RulerUnits.Inches) return 'in';
    if (u == RulerUnits.Pixels) return 'px';
    if (u == RulerUnits.Points || u == RulerUnits.Picas) return 'pt';
    return 'mm';
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
    return String(Math.round(v * fromUnit.points / toUnit.points * 1000) / 1000);
  }

  // '5', '2.5', '2,5'(쉼표 소수점), '-3' 을 숫자로 읽습니다. 숫자가 아니면 NaN
  function parseNumber(text) {
    var t = trim(text).replace(',', '.');
    return /^[+-]?(\d+\.?\d*|\.\d+)$/.test(t) ? parseFloat(t) : NaN;
  }

  function parseInteger(text) {
    var t = trim(text);
    return /^[+-]?\d+$/.test(t) ? parseInt(t, 10) : NaN;
  }

  function trim(text) {
    return String(text).replace(/^\s+|\s+$/g, '');
  }

  function clampIndex(value, length) {
    var n = parseInt(value, 10);
    return (n >= 0 && n < length) ? n : 0;
  }

  function readPreference(key, fallback) {
    try {
      return app.preferences.getBooleanPreference(key);
    } catch (e) {
      return fallback;
    }
  }

  function copyObject(source) {
    var out = {};
    for (var key in source) {
      if (source.hasOwnProperty(key)) out[key] = source[key];
    }
    return out;
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
    var result = copyObject(defaults);
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
        var key = lines[i].substring(0, eq);
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
