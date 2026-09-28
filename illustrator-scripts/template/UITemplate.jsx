//@target illustrator
/*
 * ============================================================================
 *  UI 스크립트 템플릿  (UITemplate.jsx)
 * ============================================================================
 *  창(대화상자)을 띄워 값을 입력받는 스크립트를 새로 만들 때 복사해서 쓰는 뼈대입니다.
 *  예제로 '선택한 객체를 입력한 거리만큼 이동'하는 기능이 들어 있습니다.
 *
 *  새 스크립트로 바꿀 때 고칠 곳
 *    1) SCRIPT_TITLE, SETTINGS_NAME, DEFAULTS : 이름과 처음 기본값
 *    2) showDialog()                          : 창에 넣을 입력 칸
 *    3) readOptions()                         : 입력값 읽기와 검사
 *    4) run() / revert()                      : 실제로 할 일과 그 되돌리기  <- 핵심
 *
 *  ScriptUI 에서 자주 쓰는 컨트롤 (parent.add('종류', 위치, 글자) 로 추가)
 *    'statictext' 글자        'edittext' 입력 칸      'button' 버튼
 *    'checkbox' 체크 상자     'radiobutton' 라디오     'dropdownlist' 드롭다운
 *    'slider' 슬라이더        'listbox' 목록          'progressbar' 진행 막대
 *    'panel' 제목 있는 상자   'group' 보이지 않는 묶음(줄 맞춤용)
 *
 *  자주 쓰는 이벤트
 *    onClick    : 버튼 · 체크 상자 · 라디오를 눌렀을 때
 *    onChanging : 입력 칸에 글자를 칠 때마다 / 슬라이더를 끄는 동안
 *    onChange   : 드롭다운 선택이 바뀌었을 때 / 입력을 마쳤을 때
 *
 *  주의 : 한글이 들어간 .jsx 는 'UTF-8 (BOM)' 으로 저장해야 깨지지 않습니다.
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

  // ---- 1) 이름과 기본값 --------------------------------------------------------
  var SCRIPT_TITLE = '선택 객체 이동 (템플릿 예제)';
  var SETTINGS_NAME = 'UITemplate'; // 마지막 입력값을 기억할 파일 이름
  var DEFAULTS = {                  // 처음 실행할 때의 값 (문자/숫자/참거짓)
    moveX: '10',
    moveY: '0',
    unit: 'mm',
    preview: true
  };

  // 스크립트 안에서는 길이를 모두 pt 로 계산합니다. points = 1 단위가 몇 pt 인지
  var UNITS = [
    { label: 'mm', points: 72 / 25.4 },
    { label: 'cm', points: 72 / 2.54 },
    { label: 'pt', points: 1 },
    { label: 'px', points: 1 },
    { label: 'in', points: 72 }
  ];

  try {
    main();
  } catch (e) {
    alert('스크립트 실행 중 오류가 발생했습니다.\n\n' + e.message + (e.line ? '\n(줄 ' + e.line + ')' : ''), SCRIPT_TITLE, true);
  }

  // ==========================================================================
  //  진입점: 조건 확인 → 창 띄우기 → 실행
  // ==========================================================================
  function main() {
    if (app.documents.length === 0) {
      alert('열려 있는 문서가 없습니다.\n문서를 연 뒤 다시 실행해 주세요.', SCRIPT_TITLE);
      return;
    }
    var doc = app.activeDocument;
    var items = selectedItems(doc);
    if (!items.length) {
      alert('객체를 먼저 선택해 주세요.', SCRIPT_TITLE);
      return;
    }

    // applied: 미리보기로 문서에 적용해 둔 값 (없으면 null)
    var state = { items: items, applied: null };
    var options = showDialog(loadSettings(SETTINGS_NAME, DEFAULTS), state);

    // 미리보기로 바꾼 것을 먼저 되돌린 뒤 최종 값으로 한 번에 적용합니다.
    // 이렇게 하면 실행 취소(Ctrl/Cmd+Z) 한 번으로 스크립트 실행 전으로 돌아갑니다.
    if (state.applied) {
      revert(state.items, state.applied);
      state.applied = null;
      app.redraw();
    }
    if (!options) return; // 취소
    run(state.items, options);
  }

  // ==========================================================================
  //  4) 실제로 할 일 — 이 두 함수를 원하는 기능으로 바꾸세요
  // ==========================================================================
  function run(items, o) {
    // translate(가로, 세로, 객체, 칠 패턴, 칠 그레이디언트, 선 패턴) — 패턴·그레이디언트도 함께 이동
    for (var i = 0; i < items.length; i++) items[i].translate(o.dx, o.dy, true, true, true, true);
  }

  // run() 을 되돌리는 방법 (미리보기용). 되돌리기 어려운 기능이면 미리보기 체크 상자를 빼세요.
  function revert(items, o) {
    for (var i = 0; i < items.length; i++) items[i].translate(-o.dx, -o.dy, true, true, true, true);
  }

  // ==========================================================================
  //  2) 창 만들기
  // ==========================================================================
  function showDialog(s, state) {
    var result = null;

    // 'dialog' = 확인/취소를 누를 때까지 다른 작업을 막는 창
    var win = new Window('dialog', SCRIPT_TITLE);
    win.orientation = 'column';          // 안의 요소를 세로로 쌓기 ('row' 는 가로)
    win.alignChildren = ['fill', 'top']; // [가로 맞춤, 세로 맞춤]
    win.spacing = 10;                    // 요소 사이 간격(px)
    win.margins = 16;                    // 창 안쪽 여백(px)

    // 제목 있는 상자(panel) 안에 줄(group)을 만들어 라벨과 입력 칸을 나란히 놓습니다.
    var panel = win.add('panel', undefined, '이동 거리');
    panel.orientation = 'column';
    panel.alignChildren = ['left', 'center'];
    panel.margins = [12, 16, 12, 12];

    var rowX = panel.add('group');
    rowX.add('statictext', undefined, '가로 (→ 오른쪽 +):').preferredSize.width = 120;
    var etX = rowX.add('edittext', undefined, s.moveX);
    etX.characters = 8;

    var rowY = panel.add('group');
    rowY.add('statictext', undefined, '세로 (↓ 아래쪽 +):').preferredSize.width = 120;
    var etY = rowY.add('edittext', undefined, s.moveY);
    etY.characters = 8;

    var rowUnit = panel.add('group');
    rowUnit.add('statictext', undefined, '단위:').preferredSize.width = 120;
    var ddUnit = rowUnit.add('dropdownlist', undefined, unitLabels());
    ddUnit.selection = unitIndexOf(s.unit);

    var cbPreview = win.add('checkbox', undefined, '미리보기');
    cbPreview.value = s.preview;

    var stStatus = win.add('statictext', undefined, '');
    stStatus.preferredSize.width = 300;

    var buttons = addButtons(win, '이동');

    // ---- 이벤트 연결 -------------------------------------------------------
    etX.onChanging = update;
    etY.onChanging = update;
    ddUnit.onChange = update;
    cbPreview.onClick = update;

    buttons.ok.onClick = function () {
      var o = readOptions();
      if (o.error) return;
      result = o;
      saveSettings(SETTINGS_NAME, {
        moveX: etX.text,
        moveY: etY.text,
        unit: UNITS[ddUnit.selection.index].label,
        preview: cbPreview.value
      });
      win.close(1); // show() 가 1 을 돌려줌
    };
    buttons.cancel.onClick = function () {
      win.close(2);
    };
    win.onShow = function () {
      etX.active = true; // 창이 뜨면 첫 입력 칸에 커서
    };

    update();
    win.center();
    return win.show() === 1 ? result : null;

    // ---- 3) 입력값 읽기와 검사 --------------------------------------------
    function readOptions() {
      var unit = UNITS[ddUnit.selection ? ddUnit.selection.index : 0];
      var x = parseNumber(etX.text);
      var y = parseNumber(etY.text);
      var o = { error: '' };
      if (isNaN(x) || isNaN(y)) {
        o.error = '숫자를 입력해 주세요.';
        return o;
      }
      // 화면에서는 아래쪽이 + 이지만, 스크립트 좌표는 위쪽이 + 라서 세로 값의 부호를 바꿉니다.
      o.dx = x * unit.points;
      o.dy = -y * unit.points;
      return o;
    }

    // 값이 바뀔 때마다: 상태 글자 갱신 + (미리보기면) 문서에 바로 반영
    function update() {
      var o = readOptions();
      buttons.ok.enabled = !o.error;
      stStatus.text = o.error ? '확인 필요: ' + o.error : '선택한 객체 ' + state.items.length + '개를 옮깁니다.';
      if (o.error) return;

      if (state.applied) {
        revert(state.items, state.applied);
        state.applied = null;
      }
      if (cbPreview.value) {
        run(state.items, o);
        state.applied = o;
      }
      app.redraw(); // 창이 떠 있는 동안 문서 화면을 새로 그림
    }
  }

  // ==========================================================================
  //  도우미 함수 (다른 스크립트에서도 그대로 쓸 수 있습니다)
  // ==========================================================================
  // 선택한 객체 목록. 텍스트를 편집 중이면 빈 목록
  function selectedItems(doc) {
    var sel = doc.selection;
    var list = [];
    if (!sel || sel.typename === 'TextRange') return list;
    for (var i = 0; i < sel.length; i++) list.push(sel[i]);
    return list;
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

  // '5', '2.5', '2,5'(쉼표 소수점), '-3' 을 숫자로 읽습니다. 숫자가 아니면 NaN
  function parseNumber(text) {
    var t = String(text).replace(/^\s+|\s+$/g, '').replace(',', '.');
    return /^[+-]?(\d+\.?\d*|\.\d+)$/.test(t) ? parseFloat(t) : NaN;
  }

  // 확인/취소 버튼. Windows 는 [확인][취소], macOS 는 [취소][확인] 순서가 자연스럽습니다.
  // name 을 'ok'/'cancel' 로 주면 Enter/Esc 키로도 눌립니다.
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

  // ---- 마지막 입력값 저장/불러오기 (사용자 폴더/IllustratorUIScripts/이름.ini) ----
  // ExtendScript 에는 JSON 이 없어서 '이름=값' 줄로 저장합니다.
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
