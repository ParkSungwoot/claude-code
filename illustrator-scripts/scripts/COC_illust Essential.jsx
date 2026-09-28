//@target illustrator
//@targetengine 'COCIllustEssential'
/*
 * ============================================================================
 *  COC_illust Essential  v1.0.0
 * ============================================================================
 *  정렬 패널에 없는 기능을 모은 패널입니다. 창을 띄워 둔 채로
 *  객체를 선택하고 버튼만 누르면 됩니다. (정렬 패널처럼 계속 열려 있음)
 *
 *  [간격 · 크기]
 *    가로/세로 간격 같게 : 크기가 달라도 객체 사이의 빈 간격을 똑같이
 *                         (자동: 양 끝 고정 / 직접 입력: 5 mm 처럼, 처음·가운데·끝 기준)
 *    스포이드            : 두 객체 사이의 간격을 읽어 와서 다른 곳에 똑같이 적용
 *    격자로 정리          : 흩어진 객체의 행과 열을 찾아 같은 간격의 격자로
 *    크기 맞추기          : 폭/높이를 가장 큰·가장 작은·맨 위 객체·키 오브젝트에 맞춤 (비율 유지 선택)
 *  [회전]
 *    회전                : 0°로 초기화 / 맨 위 객체 각도로 / 입력한 각도로
 *    포인트 기준 회전     : 선택한 두 점이 수직 또는 수평이 되도록 객체를 돌림
 *  [텍스트]
 *    단락 정렬 (위치 유지) : 정렬을 바꿔도 포인트 텍스트가 제자리에
 *    기준선 정렬          : 크기가 다른 글자들을 글꼴 기준선에 맞춤
 *    어간                : 띄어쓰기 간격만 넓히거나 좁힘
 *  [정리]
 *    아트보드 리어레인지   : 놓인 순서(왼쪽 위 → 오른쪽 아래)대로 번호를 다시 매기고 격자로 정리
 *    아트보드 리네이밍     : 아트보드 이름을 1, 2, 3 … 으로
 *    아트워크 트림        : 아트보드 밖으로 나간 객체만 아트보드 크기로 클리핑 마스크
 *  [측정 기준] (간격 · 격자 · 크기 · 기준선에 공통)
 *    선 두께 포함 / 글자 모양 기준(텍스트 상자 대신 실제 글자 외곽) / 클리핑 마스크는 보이는 모양 기준
 *
 *  실행 : 파일 > 스크립트 > 기타 스크립트... 에서 이 파일 선택 (패널이 열림)
 *  지원 : Adobe Illustrator CC 2017 이상 (Windows / macOS)
 *  주의 : 이 파일은 'UTF-8 (BOM)' 인코딩으로 저장해야 한글이 깨지지 않습니다.
 *
 *  구조 : 패널(팔레트) 창은 문서를 직접 고치지 못하므로, 버튼을 누르면
 *         cocEssentialCore() 함수의 코드를 BridgeTalk 으로 일러스트레이터에 보내 실행합니다.
 *         그래서 cocEssentialCore() 는 바깥 변수를 쓰지 않고, 영어(ASCII)로만 작성합니다.
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

  var SCRIPT_TITLE = 'COC_illust Essential';
  var SETTINGS_NAME = 'COC_illust_Essential';
  var PANEL_KEY = 'COCIllustEssentialPanel'; // 이미 열린 패널을 찾기 위한 이름

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
  var DIMENSIONS = ['폭', '높이', '폭과 높이'];
  var DIMENSION_KEYS = ['w', 'h', 'wh'];
  var REFERENCES = ['가장 큰 객체', '가장 작은 객체', '맨 위 객체 (레이어 순서)', '키 오브젝트'];
  var REFERENCE_KEYS = ['largest', 'smallest', 'top', 'key'];
  var BASELINES = ['가장 왼쪽 텍스트', '가장 위 기준선', '가장 아래 기준선', '평균'];
  var BASELINE_KEYS = ['left', 'top', 'bottom', 'average'];
  var JUSTIFY_NAMES = {
    LEFT: '왼쪽 정렬',
    CENTER: '가운데 정렬',
    RIGHT: '오른쪽 정렬',
    FULLJUSTIFYLASTLINELEFT: '양쪽 정렬',
    FULLJUSTIFY: '강제 양쪽 정렬'
  };
  var WORD_STEP = 10; // 어간 -/+ 버튼 한 번에 바뀌는 양 (1/1000 em)

  // 처음 실행할 때의 기본값. 이후에는 마지막으로 쓴 값을 기억합니다.
  var DEFAULTS = {
    tab: 0,
    gapMode: 'auto',
    gap: '5',
    unit: 'mm',
    anchor: 0,
    dimension: 0,
    reference: 0,
    keepRatio: true,
    angle: '0',
    baseline: 0,
    baselineOthers: false,
    wordSpacing: '0',
    artboardLayout: 'rows',
    artboardColumns: '4',
    artboardGap: '20',
    renamePad: false,
    useVisibleBounds: true,
    useGlyphBounds: false,
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
    var lastUnit = unitIndexOf(s.unit);
    var picked = null; // 스포이드로 읽은 정확한 값 { text, unit, points } (칸에는 반올림해서 보여 줌)

    var win = new Window('palette', SCRIPT_TITLE, undefined, { closeButton: true });
    win.orientation = 'column';
    win.alignChildren = ['fill', 'top'];
    win.spacing = 8;
    win.margins = 12;

    var tabs = win.add('tabbedpanel');
    tabs.alignChildren = ['fill', 'top'];
    var tabSpacing = addTab(tabs, '간격 · 크기');
    var tabRotate = addTab(tabs, '회전');
    var tabText = addTab(tabs, '텍스트');
    var tabOrganize = addTab(tabs, '정리');
    var tabList = [tabSpacing, tabRotate, tabText, tabOrganize];

    // ---- [간격 · 크기] -----------------------------------------------------
    var pGap = addPanel(tabSpacing, '간격');
    pGap.alignChildren = ['fill', 'top'];
    var gDistribute = addRow(pGap);
    var btnHorizontal = gDistribute.add('button', undefined, '가로 간격 같게');
    var btnVertical = gDistribute.add('button', undefined, '세로 간격 같게');
    btnHorizontal.preferredSize.width = 136;
    btnVertical.preferredSize.width = 136;
    btnHorizontal.helpTip = '왼쪽 → 오른쪽 순서로, 객체 사이의 빈 간격을 모두 같게 만듭니다.';
    btnVertical.helpTip = '위 → 아래 순서로, 객체 사이의 빈 간격을 모두 같게 만듭니다.';

    var gMode = addRow(pGap);
    var rbAuto = gMode.add('radiobutton', undefined, '자동 (양 끝 고정)');
    var rbFixed = gMode.add('radiobutton', undefined, '직접 입력');
    rbAuto.helpTip = '맨 앞과 맨 끝 객체는 그대로 두고, 사이 간격만 똑같이 나눕니다. (3개 이상)';
    rbFixed.helpTip = '입력한 간격으로 붙여 놓습니다. (2개 이상)';
    rbFixed.value = (s.gapMode === 'fixed');
    rbAuto.value = !rbFixed.value;

    var gGap = addRow(pGap);
    addLabel(gGap, '간격:', 40);
    var gGapInput = addRow(gGap);
    var etGap = gGapInput.add('edittext', undefined, s.gap);
    etGap.characters = 6;
    var ddUnit = gGapInput.add('dropdownlist', undefined, unitLabels());
    ddUnit.selection = lastUnit;
    var btnPick = gGap.add('button', undefined, '스포이드');
    btnPick.helpTip = '두 객체를 선택하고 누르면 그 사이 간격을 읽어 와 간격 칸에 넣습니다.';

    var gAnchor = addRow(pGap);
    addLabel(gAnchor, '기준:', 40);
    var ddAnchor = gAnchor.add('dropdownlist', undefined, ANCHORS);
    ddAnchor.selection = clampIndex(s.anchor, ANCHORS.length);
    ddAnchor.helpTip = '직접 입력한 간격으로 배열할 때 어느 쪽을 제자리에 둘지 고릅니다.';

    var btnTidy = pGap.add('button', undefined, '격자로 정리');
    btnTidy.helpTip = '흩어진 객체의 행과 열을 찾아 같은 간격의 격자로 정리합니다. 자동이면 지금 간격의 평균, 직접 입력이면 그 간격을 씁니다.';

    var pSize = addPanel(tabSpacing, '크기 맞추기');
    var gDimension = addRow(pSize);
    addLabel(gDimension, '맞출 크기:', 66);
    var ddDimension = gDimension.add('dropdownlist', undefined, DIMENSIONS);
    ddDimension.selection = clampIndex(s.dimension, DIMENSIONS.length);
    var gReference = addRow(pSize);
    addLabel(gReference, '기준 객체:', 66);
    var ddReference = gReference.add('dropdownlist', undefined, REFERENCES);
    ddReference.selection = clampIndex(s.reference, REFERENCES.length);
    ddReference.helpTip = '키 오브젝트: 여러 객체를 선택한 뒤 기준으로 쓸 객체를 한 번 더 클릭해 굵은 테두리로 만드세요.';
    var cbRatio = pSize.add('checkbox', undefined, '비율 유지');
    cbRatio.value = s.keepRatio;
    var btnSize = pSize.add('button', undefined, '크기 맞추기');

    // ---- [회전] -------------------------------------------------------------
    var pRotate = addPanel(tabRotate, '회전');
    var gRotate = addRow(pRotate);
    var btnResetRotation = gRotate.add('button', undefined, '0°로 초기화');
    var btnMatchRotation = gRotate.add('button', undefined, '맨 위 객체 각도로');
    btnResetRotation.helpTip = '돌려 놓은 객체를 똑바로(0°) 되돌립니다.';
    btnMatchRotation.helpTip = '레이어 순서상 맨 위 객체의 각도에 나머지를 맞춥니다.';
    var gAngle = addRow(pRotate);
    addLabel(gAngle, '각도:', 40);
    var etAngle = gAngle.add('edittext', undefined, s.angle);
    etAngle.characters = 5;
    gAngle.add('statictext', undefined, '°');
    var btnAngle = gAngle.add('button', undefined, '각도 적용');
    btnAngle.helpTip = '선택한 객체를 입력한 각도(반시계 방향 +)로 맞춥니다.';

    var pPoints = addPanel(tabRotate, '포인트 기준 회전');
    pPoints.alignChildren = ['fill', 'top'];
    pPoints.add('statictext', undefined, '직접 선택 도구(A)로 점 두 개를 고르세요.');
    var btnPointVertical = pPoints.add('button', undefined, '포인트 기준 수직 회전');
    var btnPointHorizontal = pPoints.add('button', undefined, '포인트 기준 수평 회전');
    btnPointVertical.helpTip = '두 점이 위아래로 똑바로 서도록 점이 속한 객체를 돌립니다. (두 점의 가운데가 중심)';
    btnPointHorizontal.helpTip = '두 점이 옆으로 나란히 놓이도록 점이 속한 객체를 돌립니다. (두 점의 가운데가 중심)';

    // ---- [텍스트] ----------------------------------------------------------
    var pJustify = addPanel(tabText, '단락 정렬 (위치 유지)');
    var gJustify = addRow(pJustify);
    var btnLeft = gJustify.add('button', undefined, '왼쪽');
    var btnCenter = gJustify.add('button', undefined, '가운데');
    var btnRight = gJustify.add('button', undefined, '오른쪽');
    var gJustify2 = addRow(pJustify);
    var btnJustify = gJustify2.add('button', undefined, '양쪽 정렬');
    var btnJustifyAll = gJustify2.add('button', undefined, '강제 양쪽');
    var justifyButtons = [btnLeft, btnCenter, btnRight, btnJustify, btnJustifyAll];
    for (var i = 0; i < justifyButtons.length; i++) justifyButtons[i].preferredSize.width = 84;
    btnLeft.helpTip = '왼쪽 정렬로 바꾸고, 글자는 제자리에 둡니다.';
    btnCenter.helpTip = '가운데 정렬로 바꾸고, 글자는 제자리에 둡니다.';
    btnRight.helpTip = '오른쪽 정렬로 바꾸고, 글자는 제자리에 둡니다.';
    btnJustify.helpTip = '양쪽 정렬(마지막 줄 왼쪽). 영역 텍스트에만 적용됩니다.';
    btnJustifyAll.helpTip = '모든 줄 양쪽 정렬. 영역 텍스트에만 적용됩니다.';

    var pBaseline = addPanel(tabText, '기준선 정렬');
    var gBaseline = addRow(pBaseline);
    addLabel(gBaseline, '기준선 위치:', 76);
    var ddBaseline = gBaseline.add('dropdownlist', undefined, BASELINES);
    ddBaseline.selection = clampIndex(s.baseline, BASELINES.length);
    var cbOthers = pBaseline.add('checkbox', undefined, '텍스트가 아닌 객체는 아랫변을 맞춤');
    cbOthers.value = s.baselineOthers;
    cbOthers.helpTip = '아이콘 같은 객체도 함께 선택했을 때, 그 아랫변을 기준선에 맞춥니다.';
    var btnBaseline = pBaseline.add('button', undefined, '기준선 맞추기');
    btnBaseline.helpTip = '가로쓰기 포인트 텍스트들의 첫 줄 기준선을 한 높이로 맞춥니다.';

    var pWord = addPanel(tabText, '어간 (띄어쓰기 간격)');
    var gWord = addRow(pWord);
    addLabel(gWord, '값:', 40);
    var etWord = gWord.add('edittext', undefined, s.wordSpacing);
    etWord.characters = 5;
    gWord.add('statictext', undefined, '/1000 em');
    var btnWordApply = gWord.add('button', undefined, '적용');
    var gWord2 = addRow(pWord);
    var btnWordMinus = gWord2.add('button', undefined, '-' + WORD_STEP);
    var btnWordPlus = gWord2.add('button', undefined, '+' + WORD_STEP);
    var btnWordReset = gWord2.add('button', undefined, '0으로');
    btnWordApply.helpTip = '선택한 텍스트의 띄어쓰기에만 자간을 입력한 값으로 줍니다. (음수면 좁게)';
    btnWordMinus.helpTip = '띄어쓰기 간격을 조금 좁힙니다.';
    btnWordPlus.helpTip = '띄어쓰기 간격을 조금 넓힙니다.';
    btnWordReset.helpTip = '띄어쓰기 간격을 원래대로(0) 되돌립니다.';

    // ---- [정리] -------------------------------------------------------------
    var pBoards = addPanel(tabOrganize, '아트보드');
    pBoards.alignChildren = ['fill', 'top'];
    var gLayout = addRow(pBoards);
    var rbRows = gLayout.add('radiobutton', undefined, '지금 행 유지');
    var rbColumns = gLayout.add('radiobutton', undefined, '열 수:');
    var etColumns = gLayout.add('edittext', undefined, s.artboardColumns);
    etColumns.characters = 3;
    rbRows.helpTip = '지금 한 줄에 놓인 아트보드들은 정리한 뒤에도 한 줄에 둡니다.';
    rbColumns.helpTip = '한 줄에 놓을 아트보드 수를 정합니다.';
    rbColumns.value = (s.artboardLayout === 'columns');
    rbRows.value = !rbColumns.value;
    var gBoardGap = addRow(pBoards);
    addLabel(gBoardGap, '간격:', 40);
    var etBoardGap = gBoardGap.add('edittext', undefined, s.artboardGap);
    etBoardGap.characters = 6;
    var stBoardUnit = gBoardGap.add('statictext', undefined, UNITS[lastUnit].label);
    stBoardUnit.preferredSize.width = 30;
    stBoardUnit.helpTip = '단위는 [간격 · 크기] 탭에서 바꿉니다.';
    var btnArrange = pBoards.add('button', undefined, '아트보드 리어레인지');
    btnArrange.helpTip = '놓인 순서(왼쪽 위 → 오른쪽 아래)대로 아트보드 번호를 다시 매기고 격자로 정리합니다. ' +
      '아트보드 위의 객체도 함께 옮기고, 잠긴 객체는 잠깐 풀었다가 다시 잠급니다.';
    var gRename = addRow(pBoards);
    var btnRename = gRename.add('button', undefined, '아트보드 리네이밍');
    var cbPad = gRename.add('checkbox', undefined, '01, 02 …');
    cbPad.value = s.renamePad;
    btnRename.helpTip = '아트보드 패널 순서대로 이름을 1, 2, 3 … 으로 바꿉니다.';
    cbPad.helpTip = '자릿수를 맞춥니다. 내보낸 파일이 이름 순서대로 정렬됩니다.';

    var pArtwork = addPanel(tabOrganize, '아트워크');
    pArtwork.alignChildren = ['fill', 'top'];
    var btnTrim = pArtwork.add('button', undefined, '아트워크 트림');
    btnTrim.helpTip = '아트보드 밖으로 나간 객체만 아트보드 크기의 클리핑 마스크로 잘라 냅니다. 잠기거나 숨긴 객체는 건너뜁니다.';

    // ---- 공통: 측정 기준 ----------------------------------------------------
    var gMeasure = addRow(win);
    var cbVisible = gMeasure.add('checkbox', undefined, '선 두께 포함');
    cbVisible.value = s.useVisibleBounds;
    cbVisible.helpTip = '선 두께까지 포함한 크기로 간격 · 격자 · 크기를 계산합니다.';
    var cbGlyph = gMeasure.add('checkbox', undefined, '글자 모양 기준');
    cbGlyph.value = s.useGlyphBounds;
    cbGlyph.helpTip = '텍스트는 텍스트 상자 대신 실제 글자 외곽을 기준으로 계산합니다.';

    var stStatus = win.add('statictext', undefined, '객체나 텍스트를 선택하고 버튼을 누르세요.', { multiline: true });
    stStatus.preferredSize = [290, 34]; // 두 줄까지 표시

    // ---- 동작 연결 ---------------------------------------------------------
    tabs.selection = tabList[clampIndex(s.tab, tabList.length)]; // 핸들러를 달기 전에 (열 때 저장하지 않도록)
    btnHorizontal.onClick = function () { distribute('h'); };
    btnVertical.onClick = function () { distribute('v'); };
    btnPick.onClick = function () { send(withMeasure({ action: 'pickgap' })); };
    btnTidy.onClick = tidy;
    btnSize.onClick = matchSize;
    btnResetRotation.onClick = function () { send({ action: 'rotate', mode: 'reset', angle: 0 }); };
    btnMatchRotation.onClick = function () { send({ action: 'rotate', mode: 'match', angle: 0 }); };
    btnPointVertical.onClick = function () { send({ action: 'pointrotate', axis: 'v' }); };
    btnPointHorizontal.onClick = function () { send({ action: 'pointrotate', axis: 'h' }); };
    btnArrange.onClick = arrangeArtboards;
    btnRename.onClick = function () {
      remember();
      send({ action: 'rename', pad: cbPad.value });
    };
    btnTrim.onClick = function () { send({ action: 'trim' }); };
    btnAngle.onClick = function () {
      var angle = parseNumber(etAngle.text);
      if (isNaN(angle)) return setStatus('각도는 숫자로 입력해 주세요.');
      remember();
      send({ action: 'rotate', mode: 'set', angle: angle });
    };
    btnLeft.onClick = function () { justify('LEFT'); };
    btnCenter.onClick = function () { justify('CENTER'); };
    btnRight.onClick = function () { justify('RIGHT'); };
    btnJustify.onClick = function () { justify('FULLJUSTIFYLASTLINELEFT'); };
    btnJustifyAll.onClick = function () { justify('FULLJUSTIFY'); };
    btnBaseline.onClick = function () {
      remember();
      send(withMeasure({ action: 'baseline', reference: BASELINE_KEYS[ddBaseline.selection.index], others: cbOthers.value }));
    };
    btnWordApply.onClick = function () {
      var value = parseNumber(etWord.text);
      if (isNaN(value)) return setStatus('어간 값은 숫자로 입력해 주세요. (예: -50, 100)');
      remember();
      send({ action: 'wordspace', mode: 'set', value: Math.round(value) });
    };
    btnWordMinus.onClick = function () { send({ action: 'wordspace', mode: 'add', value: -WORD_STEP }); };
    btnWordPlus.onClick = function () { send({ action: 'wordspace', mode: 'add', value: WORD_STEP }); };
    btnWordReset.onClick = function () {
      etWord.text = '0';
      remember();
      send({ action: 'wordspace', mode: 'set', value: 0 });
    };

    rbAuto.onClick = function () { updateEnabled(); remember(); };
    rbFixed.onClick = function () { updateEnabled(); remember(); };
    rbRows.onClick = function () { updateEnabled(); remember(); };
    rbColumns.onClick = function () { updateEnabled(); remember(); };
    ddUnit.onChange = function () {
      // 단위를 바꾸면 입력해 둔 간격 값도 새 단위로 환산합니다.
      if (!ddUnit.selection || ddUnit.selection.index === lastUnit) return;
      var next = ddUnit.selection.index;
      etGap.text = convertText(etGap.text, UNITS[lastUnit], UNITS[next]);
      etBoardGap.text = convertText(etBoardGap.text, UNITS[lastUnit], UNITS[next]);
      stBoardUnit.text = UNITS[next].label;
      lastUnit = next;
      remember();
    };
    var remembered = [ddAnchor, ddDimension, ddReference, ddBaseline, tabs];
    for (i = 0; i < remembered.length; i++) remembered[i].onChange = remember;
    var rememberedClicks = [cbRatio, cbOthers, cbPad, cbVisible, cbGlyph];
    for (i = 0; i < rememberedClicks.length; i++) rememberedClicks[i].onClick = remember;
    etGap.onChange = remember;
    etAngle.onChange = remember;
    etWord.onChange = remember;
    etColumns.onChange = remember;
    etBoardGap.onChange = remember;

    win.onClose = function () {
      remember();
      $.global[PANEL_KEY] = null;
      return true;
    };

    updateEnabled();
    placeWindow(win, s.windowX, s.windowY);
    $.global[PANEL_KEY] = win;
    win.show();

    // ---- 버튼 동작 ---------------------------------------------------------
    // 단위는 자동 모드에서도 결과 표시와 스포이드에 쓰이므로 숫자 칸과 기준만 끕니다.
    function updateEnabled() {
      etGap.enabled = rbFixed.value;
      gAnchor.enabled = rbFixed.value;
      etColumns.enabled = rbColumns.value;
    }

    // 간격 · 격자 · 크기 · 기준선에 공통으로 쓰는 측정 기준을 요청에 붙입니다.
    function withMeasure(request) {
      request.visible = cbVisible.value;
      request.glyph = cbGlyph.value;
      return request;
    }

    // 직접 입력 모드면 간격 값을 pt 로 읽습니다. 숫자가 아니면 NaN
    function gapPoints() {
      if (!rbFixed.value) return 0;
      if (picked && picked.text === etGap.text && picked.unit === lastUnit) return picked.points;
      var gap = parseNumber(etGap.text);
      return isNaN(gap) ? NaN : gap * UNITS[lastUnit].points;
    }

    function distribute(axis) {
      var gap = gapPoints();
      if (isNaN(gap)) return setStatus('간격은 숫자로 입력해 주세요.');
      remember();
      send(withMeasure({
        action: 'distribute',
        axis: axis,
        mode: rbFixed.value ? 'fixed' : 'auto',
        gap: gap,
        anchor: ANCHOR_KEYS[ddAnchor.selection ? ddAnchor.selection.index : 0]
      }));
    }

    function tidy() {
      var gap = gapPoints();
      if (isNaN(gap)) return setStatus('간격은 숫자로 입력해 주세요.');
      remember();
      send(withMeasure({ action: 'tidy', mode: rbFixed.value ? 'fixed' : 'auto', gap: gap }));
    }

    function matchSize() {
      remember();
      send(withMeasure({
        action: 'matchsize',
        dimension: DIMENSION_KEYS[ddDimension.selection.index],
        reference: REFERENCE_KEYS[ddReference.selection.index],
        keepRatio: cbRatio.value
      }));
    }

    function justify(name) {
      send({ action: 'justify', justification: name });
    }

    function arrangeArtboards() {
      var gap = parseNumber(etBoardGap.text);
      if (isNaN(gap) || gap < 0) return setStatus('아트보드 간격은 0 이상의 숫자로 입력해 주세요.');
      var columns = 0;
      if (rbColumns.value) {
        columns = parseNumber(etColumns.text);
        if (isNaN(columns) || columns < 1 || Math.round(columns) !== columns) return setStatus('열 수는 1 이상의 정수로 입력해 주세요.');
      }
      remember();
      send({ action: 'arrange', columns: columns, gap: gap * UNITS[lastUnit].points });
    }

    // cocEssentialCore() 의 코드와 요청 값을 문자열로 만들어 일러스트레이터에 보냅니다.
    function send(request) {
      try {
        var bt = new BridgeTalk();
        bt.target = BridgeTalk.appSpecifier || 'illustrator';
        bt.body = '(' + cocEssentialCore.toString() + ')(' + serialize(request) + ');';
        bt.onResult = function (result) {
          handleResult(request, String(result.body));
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

    // 결과 코드 → 패널 갱신과 한글 안내 문구
    function handleResult(request, body) {
      var p = body.split('|');
      var unit = UNITS[lastUnit];
      if (p[0] === 'err') return setStatus(errorText(p, body));

      if (p[1] === 'dist') {
        var what = request.axis === 'h' ? '가로' : '세로';
        return setStatus(what + ' ' + p[2] + '개를 간격 ' + lengthText(p[3]) + '로 배열했습니다.');
      }
      if (p[1] === 'gap') {
        // 스포이드: 읽은 간격을 입력 칸에 넣고 '직접 입력'으로 바꿔 둡니다.
        var axisName = p[2] === 'h' ? '가로' : '세로';
        var gap = parseFloat(p[3]);
        etGap.text = formatNumber(gap / unit.points);
        picked = { text: etGap.text, unit: lastUnit, points: gap };
        rbFixed.value = true;
        rbAuto.value = false;
        updateEnabled();
        remember();
        return setStatus(axisName + ' 간격을 가져왔습니다: ' + etGap.text + ' ' + unit.label + (gap < 0 ? ' (겹쳐 있음)' : '') +
          '\n다른 객체를 선택하고 [' + axisName + ' 간격 같게]를 누르세요.');
      }
      if (p[1] === 'tidy') {
        return setStatus('격자로 정리했습니다: ' + p[2] + '개, ' + p[3] + '행 × ' + p[4] + '열\n간격 가로 ' +
          lengthText(p[5]) + ' · 세로 ' + lengthText(p[6]));
      }
      if (p[1] === 'size') {
        var dimension = request.dimension === 'w' ? '폭 ' + lengthText(p[4]) :
          (request.dimension === 'h' ? '높이 ' + lengthText(p[5]) : '폭 ' + lengthText(p[4]) + ' · 높이 ' + lengthText(p[5]));
        var sizeText = '크기를 맞췄습니다: ' + p[2] + '개 → ' + dimension;
        if (parseInt(p[3], 10)) sizeText += '\n크기가 0이라 건너뛴 객체 ' + p[3] + '개';
        return setStatus(sizeText);
      }
      if (p[1] === 'rot') {
        var done = p[3];
        var rotateText;
        if (p[2] === 'reset') rotateText = '회전을 0°로 초기화했습니다: ' + done + '개';
        else if (p[2] === 'match') rotateText = '맨 위 객체 각도(' + formatNumber(parseFloat(p[6])) + '°)로 맞췄습니다: ' + done + '개';
        else rotateText = formatNumber(parseFloat(p[6])) + '°로 맞췄습니다: ' + done + '개';
        if (parseInt(p[4], 10)) rotateText += '\n회전 정보가 없는 ' + p[4] + '개는 그대로 두었습니다.';
        if (parseInt(p[5], 10)) rotateText += '\n' + p[5] + '개 실패 (잠긴 객체?)';
        return setStatus(rotateText);
      }
      if (p[1] === 'prot') {
        var pointAxis = p[2] === 'v' ? '수직' : '수평';
        if (!parseFloat(p[3])) return setStatus('두 점이 이미 ' + pointAxis + '입니다.');
        var pointText = '두 점이 ' + pointAxis + '이 되도록 ' + formatNumber(parseFloat(p[3])) + '° 돌렸습니다: 객체 ' + p[4] + '개';
        if (parseInt(p[5], 10)) pointText += '\n잠긴 객체라 돌리지 못한 것이 있습니다.';
        return setStatus(pointText);
      }
      if (p[1] === 'arrange') {
        var arrangeText = '아트보드 ' + p[2] + '개를 ' + p[3] + '행 × ' + p[4] + '열로 정리하고, 놓인 순서대로 번호를 다시 매겼습니다.';
        if (parseInt(p[5], 10)) arrangeText += '\n잠긴 것 ' + p[5] + '개는 잠깐 풀었다가 다시 잠갔습니다.';
        if (parseInt(p[6], 10)) arrangeText += '\n객체 ' + p[6] + '개는 옮기지 못했습니다.';
        return setStatus(arrangeText);
      }
      if (p[1] === 'rename') {
        return setStatus('아트보드 이름을 바꿨습니다: ' + p[3] + ' ~ ' + p[4] + ' (' + p[2] + '개)');
      }
      if (p[1] === 'trim') {
        var trimText = parseInt(p[2], 10) ? '아트보드 밖으로 나간 객체 ' + p[2] + '개를 아트보드 크기로 잘랐습니다.' :
          '아트보드 밖으로 나간 객체가 없습니다.';
        if (parseInt(p[3], 10)) trimText += '\n잠기거나 숨긴 객체 ' + p[3] + '개는 건너뛰었습니다.';
        if (parseInt(p[5], 10)) trimText += '\n' + p[5] + '개 실패';
        return setStatus(trimText);
      }
      if (p[1] === 'just') {
        var parts = [];
        if (parseInt(p[2], 10)) parts.push('포인트 ' + p[2] + '개(제자리 유지)');
        if (parseInt(p[3], 10)) parts.push('영역 ' + p[3] + '개');
        if (parseInt(p[4], 10)) parts.push('패스 ' + p[4] + '개(위치 유지 안 됨)');
        var justText = JUSTIFY_NAMES[request.justification] + ': ' + (parts.length ? parts.join(', ') : '바뀐 텍스트 없음');
        if (parseInt(p[5], 10)) justText += ' / 포인트 텍스트 ' + p[5] + '개는 양쪽 정렬을 쓸 수 없어 건너뜀';
        if (parseInt(p[6], 10)) justText += ' / ' + p[6] + '개 실패';
        return setStatus(justText);
      }
      if (p[1] === 'base') {
        var baseText = '기준선을 맞췄습니다: 텍스트 ' + p[2] + '개';
        if (parseInt(p[3], 10)) baseText += ', 객체 ' + p[3] + '개';
        if (parseInt(p[4], 10)) baseText += '\n영역 · 패스 · 세로 텍스트 ' + p[4] + '개는 제외했습니다.';
        return setStatus(baseText);
      }
      if (p[1] === 'word') {
        if (!parseInt(p[2], 10)) return setStatus('선택한 텍스트에 띄어쓰기가 없습니다.');
        if (p[3] !== '') {
          etWord.text = p[3];
          remember();
        }
        return setStatus('어간 ' + p[3] + ' 적용: 띄어쓰기 ' + p[2] + '개');
      }
      return setStatus(body);
    }

    function errorText(p, body) {
      if (p[1] === 'nodoc') return '열린 문서가 없습니다.';
      if (p[1] === 'textedit') return '텍스트 편집 중입니다. Esc 로 편집을 끝낸 뒤 다시 누르세요.';
      if (p[1] === 'few') return '객체를 ' + p[2] + '개 이상 선택하세요.';
      if (p[1] === 'two') return '간격을 잴 두 객체를 선택하세요.';
      if (p[1] === 'notext') return '텍스트를 선택하세요. (그룹 안의 텍스트도 됩니다)';
      if (p[1] === 'nopoint') return '가로쓰기 포인트 텍스트를 선택하세요.';
      if (p[1] === 'nokey') return '키 오브젝트를 찾지 못했습니다. 여러 객체를 선택한 뒤 기준 객체를 한 번 더 클릭해 굵은 테두리로 만드세요.';
      if (p[1] === 'points') return '점을 정확히 두 개 선택하세요. (지금 ' + (p[2] === 'many' ? '3개 이상' : p[2] + '개') + ') 직접 선택 도구(A)를 쓰세요.';
      if (p[1] === 'samepoint') return '두 점이 같은 위치에 있습니다. 떨어진 두 점을 고르세요.';
      if (p[1] === 'canvas') return '아트보드가 캔버스 밖으로 나가서 정리하지 못했습니다. 간격을 줄이거나 열 수를 바꿔 보세요.';
      if (p[1] === 'exception') return '오류: ' + safeDecode(p[2]);
      return '알 수 없는 결과: ' + body;
    }

    // pt 값을 지금 단위의 글자로 (예: '5 mm')
    function lengthText(points) {
      var unit = UNITS[lastUnit];
      return formatNumber(parseFloat(points) / unit.points) + ' ' + unit.label;
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
      var tabIndex = 0;
      for (var k = 0; k < tabList.length; k++) {
        if (tabs.selection === tabList[k]) tabIndex = k;
      }
      saveSettings(SETTINGS_NAME, {
        tab: tabIndex,
        gapMode: rbFixed.value ? 'fixed' : 'auto',
        gap: etGap.text,
        unit: UNITS[lastUnit].label,
        anchor: ddAnchor.selection ? ddAnchor.selection.index : 0,
        dimension: ddDimension.selection ? ddDimension.selection.index : 0,
        reference: ddReference.selection ? ddReference.selection.index : 0,
        keepRatio: cbRatio.value,
        angle: etAngle.text,
        baseline: ddBaseline.selection ? ddBaseline.selection.index : 0,
        baselineOthers: cbOthers.value,
        wordSpacing: etWord.text,
        artboardLayout: rbColumns.value ? 'columns' : 'rows',
        artboardColumns: etColumns.text,
        artboardGap: etBoardGap.text,
        renamePad: cbPad.value,
        useVisibleBounds: cbVisible.value,
        useGlyphBounds: cbGlyph.value,
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
  function cocEssentialCore(req) {
    var NBSP = String.fromCharCode(0xA0);
    var IDEOGRAPHIC_SPACE = String.fromCharCode(0x3000);
    var matrixSigns = {}; // per kind of object: 1 or -1, how its matrix reports rotation (see probeMatrixSign)
    try {
      if (app.documents.length === 0) return 'err|nodoc';
      var sel = app.activeDocument.selection;
      switch (req.action) {
        case 'distribute': return distribute(sel, req);
        case 'pickgap': return pickGap(sel, req);
        case 'tidy': return tidy(sel, req);
        case 'matchsize': return matchSize(sel, req);
        case 'rotate': return rotateItems(sel, req);
        case 'pointrotate': return pointRotate(sel, req);
        case 'justify': return justify(sel, req);
        case 'baseline': return baseline(sel, req);
        case 'wordspace': return wordSpace(sel, req);
        case 'arrange': return inDocumentCoordinates(function () { return arrange(req); });
        case 'rename': return renameBoards(req);
        case 'trim': return inDocumentCoordinates(trim);
      }
      return 'err|exception|' + encodeURIComponent('unknown action ' + req.action);
    } catch (e) {
      return 'err|exception|' + encodeURIComponent(String(e.message || e));
    }

    // ---- Selection and measuring ------------------------------------------
    // Selected objects as an array, or null while the user is editing text.
    function objects(sel) {
      if (sel && sel.typename === 'TextRange') return null;
      var list = [];
      for (var i = 0; sel && i < sel.length; i++) list.push(sel[i]);
      return list;
    }

    function measure(item, index, o) {
      var b = boundsOf(item, o);
      return { ref: item, index: index, b: b, w: b[2] - b[0], h: b[1] - b[3], cx: (b[0] + b[2]) / 2, cy: (b[1] + b[3]) / 2 };
    }

    function measureAll(list, o) {
      var out = [];
      for (var i = 0; i < list.length; i++) out.push(measure(list[i], i, o));
      return out;
    }

    // [left, top, right, bottom]; clipping groups use the mask, text can use its glyph shapes.
    function boundsOf(item, o) {
      if (o.glyph) {
        var glyph = glyphBounds(item, o.visible);
        if (glyph) return glyph;
      }
      var target = item;
      if (item.typename === 'GroupItem' && item.clipped) {
        var mask = clippingPath(item);
        if (mask) target = mask;
      }
      var r = o.visible ? target.visibleBounds : target.geometricBounds;
      return [r[0], r[1], r[2], r[3]];
    }

    function clippingPath(group) {
      for (var k = 0; k < group.pageItems.length; k++) {
        var child = group.pageItems[k];
        if ((child.typename === 'PathItem' && child.clipping) ||
          (child.typename === 'CompoundPathItem' && child.pathItems.length && child.pathItems[0].clipping)) return child;
      }
      return null;
    }

    // Text measured by the shape of its letters: outline a temporary copy, measure it, delete it.
    function glyphBounds(item, visible) {
      var isText = item.typename === 'TextFrame';
      var isTextGroup = item.typename === 'GroupItem' && !item.clipped && item.textFrames.length > 0;
      if (!isText && !isTextGroup) return null;
      var copy = null;
      try {
        copy = item.duplicate();
        copy.selected = false;
        if (isText) {
          copy = copy.createOutline();
        } else {
          for (var k = copy.textFrames.length - 1; k >= 0; k--) copy.textFrames[k].createOutline();
        }
        if (!copy.pageItems.length) return null;
        var r = visible ? copy.visibleBounds : copy.geometricBounds;
        return [r[0], r[1], r[2], r[3]];
      } catch (e) {
        return null;
      } finally {
        try {
          if (copy) copy.remove();
        } catch (e2) { /* already gone */ }
      }
    }

    function move(item, dx, dy, patterns) {
      if (Math.abs(dx) > 1e-6 || Math.abs(dy) > 1e-6) item.translate(dx, dy, true, patterns, true, patterns);
    }

    function preference(key, fallback) {
      try {
        return app.preferences.getBooleanPreference(key);
      } catch (e) {
        return fallback;
      }
    }

    function median(values) {
      var sorted = values.slice(0);
      sorted.sort(function (a, b) { return a - b; });
      return sorted.length ? sorted[Math.floor(sorted.length / 2)] : 0;
    }

    // ---- Equal gaps ---------------------------------------------------------
    // Travel coordinate t: x for horizontal, -y for vertical (so t grows to the right / downwards).
    function distribute(sel, o) {
      var list = objects(sel);
      if (list === null) return 'err|textedit';
      var minimum = o.mode === 'fixed' ? 2 : 3;
      if (list.length < minimum) return 'err|few|' + minimum;
      var items = measureAll(list, o);
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
      var i;
      for (i = 0; i < items.length; i++) {
        var it = items[i];
        it.lead = horizontal ? it.b[0] : -it.b[1];
        it.size = horizontal ? it.w : it.h;
        if (it.lead < start) start = it.lead;
        if (it.lead + it.size > end) end = it.lead + it.size;
        total += it.size;
      }

      var gap;
      var pos = start;
      if (o.mode === 'fixed') {
        gap = o.gap;
        var span = total + gap * (items.length - 1);
        if (o.anchor === 'end') pos = end - span;
        else if (o.anchor === 'center') pos = (start + end - span) / 2;
      } else {
        gap = (end - start - total) / (items.length - 1);
      }

      var patterns = preference('transformPatterns', true);
      for (i = 0; i < items.length; i++) {
        var delta = pos - items[i].lead;
        if (horizontal) move(items[i].ref, delta, 0, patterns);
        else move(items[i].ref, 0, -delta, patterns);
        pos += items[i].size + gap;
      }
      return 'ok|dist|' + items.length + '|' + gap;
    }

    // ---- Gap eyedropper: the empty space between two objects ----------------
    function pickGap(sel, o) {
      var list = objects(sel);
      if (list === null) return 'err|textedit';
      if (list.length !== 2) return 'err|two';
      var a = measure(list[0], 0, o);
      var b = measure(list[1], 1, o);
      var overlapX = Math.min(a.b[2], b.b[2]) - Math.max(a.b[0], b.b[0]);
      var overlapY = Math.min(a.b[1], b.b[1]) - Math.max(a.b[3], b.b[3]);
      var axis;
      if (overlapY > 0 && overlapX <= 0) axis = 'h';       // side by side
      else if (overlapX > 0 && overlapY <= 0) axis = 'v';  // one above the other
      else axis = Math.abs(a.cx - b.cx) >= Math.abs(a.cy - b.cy) ? 'h' : 'v';
      return 'ok|gap|' + axis + '|' + (axis === 'h' ? -overlapX : -overlapY);
    }

    // ---- Tidy up: find rows, then lay everything out on an even grid ---------
    function tidy(sel, o) {
      var list = objects(sel);
      if (list === null) return 'err|textedit';
      if (list.length < 2) return 'err|few|2';
      var items = measureAll(list, o);
      var i;
      var j;

      // rows: similar vertical centres, top to bottom; left to right inside each row
      var heights = [];
      for (i = 0; i < items.length; i++) heights.push(items[i].h);
      var tolerance = median(heights) / 2;
      var sorted = items.slice(0);
      sorted.sort(function (a, b) {
        if (Math.abs(b.cy - a.cy) > 1e-6) return b.cy - a.cy;
        return (a.cx - b.cx) || (a.index - b.index);
      });
      var rows = [];
      var row = null;
      var rowY = 0;
      for (i = 0; i < sorted.length; i++) {
        if (row && Math.abs(sorted[i].cy - rowY) <= tolerance) {
          row.push(sorted[i]);
        } else {
          row = [sorted[i]];
          rows.push(row);
          rowY = sorted[i].cy;
        }
      }
      var columns = 0;
      for (i = 0; i < rows.length; i++) {
        rows[i].sort(function (a, b) { return (a.cx - b.cx) || (a.index - b.index); });
        if (rows[i].length > columns) columns = rows[i].length;
      }

      // gaps: the typed value, or the average of the gaps that are there now
      var gapX = o.gap;
      var gapY = o.gap;
      if (o.mode !== 'fixed') {
        var sumX = 0;
        var countX = 0;
        var sumY = 0;
        var countY = 0;
        for (i = 0; i < rows.length; i++) {
          for (j = 1; j < rows[i].length; j++) {
            sumX += rows[i][j].b[0] - rows[i][j - 1].b[2];
            countX++;
          }
          if (i > 0) {
            sumY += lowestBottom(rows[i - 1]) - highestTop(rows[i]);
            countY++;
          }
        }
        gapX = countX ? Math.max(0, sumX / countX) : 0;
        gapY = countY ? Math.max(0, sumY / countY) : gapX;
        if (!countX) gapX = gapY;
      }

      // column widths, row heights and the top-left corner of the selection
      var colWidth = [];
      var rowHeight = [];
      var left = Infinity;
      var top = -Infinity;
      for (j = 0; j < columns; j++) colWidth[j] = 0;
      for (i = 0; i < rows.length; i++) {
        rowHeight[i] = 0;
        for (j = 0; j < rows[i].length; j++) {
          var it = rows[i][j];
          if (it.w > colWidth[j]) colWidth[j] = it.w;
          if (it.h > rowHeight[i]) rowHeight[i] = it.h;
          if (it.b[0] < left) left = it.b[0];
          if (it.b[1] > top) top = it.b[1];
        }
      }
      var colX = [left];
      for (j = 1; j < columns; j++) colX[j] = colX[j - 1] + colWidth[j - 1] + gapX;

      // each object sits in the middle of its cell
      var patterns = preference('transformPatterns', true);
      var y = top;
      for (i = 0; i < rows.length; i++) {
        for (j = 0; j < rows[i].length; j++) {
          var cell = rows[i][j];
          move(cell.ref, colX[j] + (colWidth[j] - cell.w) / 2 - cell.b[0], y - (rowHeight[i] - cell.h) / 2 - cell.b[1], patterns);
        }
        y -= rowHeight[i] + gapY;
      }
      return 'ok|tidy|' + items.length + '|' + rows.length + '|' + columns + '|' + gapX + '|' + gapY;
    }

    function lowestBottom(row) {
      var value = Infinity;
      for (var k = 0; k < row.length; k++) value = Math.min(value, row[k].b[3]);
      return value;
    }

    function highestTop(row) {
      var value = -Infinity;
      for (var k = 0; k < row.length; k++) value = Math.max(value, row[k].b[1]);
      return value;
    }

    // ---- Match size ---------------------------------------------------------
    function matchSize(sel, o) {
      var list = objects(sel);
      if (list === null) return 'err|textedit';
      if (list.length < 2) return 'err|few|2';
      var key = -1;
      if (o.reference === 'key') {
        key = keyObjectIndex(list);
        if (key < 0) return 'err|nokey';
      }
      var items = measureAll(list, o);
      var ref = items[key < 0 ? 0 : key]; // 'top': first in the selection = top of the stacking order
      var i;
      if (o.reference === 'largest' || o.reference === 'smallest') {
        for (i = 1; i < items.length; i++) {
          var value = sizeMetric(items[i], o.dimension);
          var best = sizeMetric(ref, o.dimension);
          if (o.reference === 'largest' ? value > best : value < best) ref = items[i];
        }
      }
      var strokes = preference('scaleLineWeight', false);
      var patterns = preference('transformPatterns', true);
      var done = 0;
      var skipped = 0;
      for (i = 0; i < items.length; i++) {
        var it = items[i];
        if (it === ref) continue;
        var widthNeeded = o.dimension !== 'h' || o.keepRatio;
        var heightNeeded = o.dimension !== 'w' || o.keepRatio;
        if ((widthNeeded && it.w <= 0) || (heightNeeded && it.h <= 0)) {
          skipped++;
          continue;
        }
        resizeTo(it, targetSize(it, ref, o), o, strokes, patterns);
        done++;
      }
      return 'ok|size|' + done + '|' + skipped + '|' + ref.w + '|' + ref.h;
    }

    // Scripts cannot read the key object, so run the Align panel commands (which align to it) and find the
    // object that never moves; then put everything back. The same trick as alignEx by Alexander Ladygin.
    function keyObjectIndex(list) {
      var commands = ['Vertical Align Top', 'Horizontal Align Right', 'Vertical Align Bottom', 'Horizontal Align Left'];
      var start = [];
      var still = [];
      var i;
      for (i = 0; i < list.length; i++) {
        var b = list[i].geometricBounds;
        start.push([b[0], b[1], b[2], b[3]]);
        still.push(true);
      }
      try {
        for (var c = 0; c < commands.length; c++) {
          app.executeMenuCommand(commands[c]);
          for (i = 0; i < list.length; i++) {
            if (still[i] && !sameBounds(list[i].geometricBounds, start[i])) still[i] = false;
          }
        }
      } finally {
        var patterns = preference('transformPatterns', true);
        for (i = 0; i < list.length; i++) {
          var now = list[i].geometricBounds;
          move(list[i], start[i][0] - now[0], start[i][1] - now[1], patterns);
        }
      }
      // Objects that never moved all have the key object's bounds. Different sizes mean the commands did nothing.
      var found = -1;
      for (i = 0; i < list.length; i++) {
        if (!still[i]) continue;
        if (found < 0) found = i;
        else if (!sameBounds(start[i], start[found])) return -1;
      }
      return found;
    }

    function sameBounds(a, b) {
      for (var k = 0; k < 4; k++) {
        if (Math.abs(a[k] - b[k]) > 0.001) return false;
      }
      return true;
    }

    function sizeMetric(it, dimension) {
      if (dimension === 'w') return it.w;
      if (dimension === 'h') return it.h;
      return it.w * it.h;
    }

    function targetSize(it, ref, o) {
      var sx = it.w > 0 ? ref.w / it.w : 1;
      var sy = it.h > 0 ? ref.h / it.h : 1;
      if (o.dimension === 'w') sy = o.keepRatio ? sx : 1;
      else if (o.dimension === 'h') sx = o.keepRatio ? sy : 1;
      else if (o.keepRatio) sx = sy = Math.min(sx, sy);
      return { w: it.w * sx, h: it.h * sy };
    }

    // Scale around the centre, then measure again and correct: strokes and text rarely scale exactly.
    function resizeTo(it, goal, o, strokes, patterns) {
      for (var pass = 0; pass < 4; pass++) {
        var sx = it.w > 0 ? goal.w / it.w : 1;
        var sy = it.h > 0 ? goal.h / it.h : 1;
        if (Math.abs(sx - 1) < 1e-5 && Math.abs(sy - 1) < 1e-5) return;
        var lines = strokes ? Math.sqrt(sx * sy) * 100 : 100;
        it.ref.resize(sx * 100, sy * 100, true, patterns, true, patterns, lines, Transformation.CENTER);
        var m = measure(it.ref, it.index, o);
        it.b = m.b;
        it.w = m.w;
        it.h = m.h;
      }
    }

    // ---- Rotation -----------------------------------------------------------
    function rotateItems(sel, o) {
      var list = objects(sel);
      if (list === null) return 'err|textedit';
      if (!list.length) return 'err|few|1';
      if (o.mode === 'match' && list.length < 2) return 'err|few|2';
      var patterns = preference('transformPatterns', true);
      var reference = 0;
      if (o.mode === 'match') {
        reference = angleOf(list[0]);
        if (reference === null) reference = 0;
      }
      var done = 0;
      var unknown = 0;
      var failed = 0;
      for (var i = (o.mode === 'match' ? 1 : 0); i < list.length; i++) {
        var current = angleOf(list[i]);
        if (current === null) {
          if (o.mode === 'reset') {
            unknown++;
            continue;
          }
          current = 0;
        }
        var target = o.mode === 'reset' ? 0 : (o.mode === 'set' ? o.angle : reference);
        try {
          var delta = normalizeAngle(target - current);
          if (Math.abs(delta) > 1e-6) list[i].rotate(delta, true, patterns, true, patterns, Transformation.CENTER);
          writeRotation(list[i], target);
          done++;
        } catch (e) {
          failed++;
        }
      }
      var shown = o.mode === 'match' ? reference : (o.mode === 'set' ? normalizeAngle(o.angle) : 0);
      return 'ok|rot|' + o.mode + '|' + done + '|' + unknown + '|' + failed + '|' + shown;
    }

    // Turn the objects that own two selected anchor points so the points line up vertically ('v') or
    // horizontally ('h'), by the smallest angle, about the middle of the two points.
    function pointRotate(sel, o) {
      var list = objects(sel);
      if (list === null) return 'err|textedit';
      var points = [];
      for (var i = 0; i < list.length && points.length <= 2; i++) collectPoints(list[i], points);
      if (points.length !== 2) return 'err|points|' + (points.length > 2 ? 'many' : points.length);
      var a = anchorOf(points[0]);
      var b = anchorOf(points[1]);
      var dx = b[0] - a[0];
      var dy = b[1] - a[1];
      if (Math.sqrt(dx * dx + dy * dy) < 1e-6) return 'err|samepoint';
      var delta = (o.axis === 'v' ? 90 : 0) - Math.atan2(dy, dx) * 180 / Math.PI;
      delta = delta - 180 * Math.round(delta / 180); // the smallest turn: -90 .. 90
      if (Math.abs(delta) < 1e-6) return 'ok|prot|' + o.axis + '|0|0|0';
      var middle = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
      var patterns = preference('transformPatterns', true);
      var done = 0;
      var failed = 0;
      var starts = [a, b];
      for (var k = 0; k < 2; k++) {
        var now = anchorOf(points[k]);
        // the second point already turned with the first object: both points belong to it
        if (k === 1 && (Math.abs(now[0] - starts[1][0]) > 1e-6 || Math.abs(now[1] - starts[1][1]) > 1e-6)) break;
        var owner = topLevel(points[k].path);
        try {
          owner.rotate(delta, true, patterns, true, patterns, Transformation.CENTER);
          var turned = anchorOf(points[k]);
          var goal = turnAround(starts[k], middle, delta);
          move(owner, goal[0] - turned[0], goal[1] - turned[1], patterns);
          shiftRotationTag(owner, delta);
          done++;
        } catch (e) {
          failed++;
        }
      }
      return 'ok|prot|' + o.axis + '|' + delta + '|' + done + '|' + failed;
    }

    // Selected anchor points (Direct Selection tool) as { path, index }; stops once there are more than two.
    function collectPoints(item, out) {
      var k;
      if (item.typename === 'PathItem') {
        var pts = item.pathPoints;
        for (k = 0; k < pts.length && out.length <= 2; k++) {
          if (pts[k].selected == PathPointSelection.ANCHORPOINT) out.push({ path: item, index: k });
        }
      } else if (item.typename === 'CompoundPathItem') {
        for (k = 0; k < item.pathItems.length && out.length <= 2; k++) collectPoints(item.pathItems[k], out);
      } else if (item.typename === 'GroupItem') {
        for (k = 0; k < item.pageItems.length && out.length <= 2; k++) collectPoints(item.pageItems[k], out);
      }
    }

    function anchorOf(point) {
      var p = point.path.pathPoints[point.index].anchor;
      return [p[0], p[1]];
    }

    // The whole object as the Selection tool sees it: climb out of groups and compound paths up to the layer.
    function topLevel(item) {
      var top = item;
      while (top.parent.typename !== 'Layer') top = top.parent;
      return top;
    }

    function turnAround(p, c, degrees) {
      var r = degrees * Math.PI / 180;
      var x = p[0] - c[0];
      var y = p[1] - c[1];
      return [c[0] + x * Math.cos(r) - y * Math.sin(r), c[1] + x * Math.sin(r) + y * Math.cos(r)];
    }

    // Objects already turned in Illustrator keep their angle in the Transform panel; follow the turn there.
    // Objects without that record stay without it, so a straightened object gets an upright bounding box.
    function shiftRotationTag(item, delta) {
      try {
        var tag = item.tags.getByName('BBAccumRotation');
        var degrees = normalizeAngle(parseFloat(tag.value) * 180 / Math.PI + delta);
        if (Math.abs(degrees) < 1e-6) tag.remove();
        else tag.value = String(degrees * Math.PI / 180);
      } catch (e) { /* no rotation recorded */ }
    }

    // Rotation as shown in the Transform panel (degrees, counter-clockwise), or null when unknown.
    // Text and images carry a matrix; other objects only remember it in the BBAccumRotation tag.
    function angleOf(item) {
      var type = item.typename;
      if (type === 'TextFrame' || type === 'PlacedItem' || type === 'RasterItem') {
        try {
          return matrixAngle(item);
        } catch (e) { /* fall back to the tag */ }
      }
      try {
        var value = parseFloat(item.tags.getByName('BBAccumRotation').value);
        return isNaN(value) ? null : normalizeAngle(value * 180 / Math.PI);
      } catch (e2) {
        return null;
      }
    }

    function matrixAngle(item) {
      var key = item.typename === 'TextFrame' ? 'TextFrame ' + item.kind : item.typename;
      if (!matrixSigns[key]) matrixSigns[key] = probeMatrixSign(item);
      return normalizeAngle(matrixSigns[key] * rawMatrixAngle(item));
    }

    // Which way the matrix reports rotation: turn a temporary copy 10 degrees and read it again.
    // Throws when the matrix does not follow rotation at all; the caller then uses the tag.
    function probeMatrixSign(item) {
      var probe = item.duplicate();
      try {
        var before = rawMatrixAngle(probe);
        probe.rotate(10, true, false, false, false, Transformation.CENTER);
        var change = normalizeAngle(rawMatrixAngle(probe) - before);
        if (Math.abs(change - 10) < 1) return 1;
        if (Math.abs(change + 10) < 1) return -1;
        throw new Error('matrix does not follow rotation');
      } finally {
        probe.remove();
      }
    }

    function rawMatrixAngle(item) {
      var m = item.matrix;
      // Mirrored objects read the other way round. Embedded images always carry a vertical flip.
      var mirrored = (m.mValueA * m.mValueD - m.mValueB * m.mValueC < 0) !== (item.typename === 'RasterItem');
      return Math.atan2(mirrored ? -m.mValueB : m.mValueB, mirrored ? -m.mValueA : m.mValueA) * 180 / Math.PI;
    }

    // Keep the Transform panel angle in step (Illustrator does not update it for scripted rotations).
    function writeRotation(item, degrees) {
      var radians = normalizeAngle(degrees) * Math.PI / 180;
      var tag = null;
      try {
        tag = item.tags.getByName('BBAccumRotation');
      } catch (e) {
        tag = null;
      }
      try {
        if (Math.abs(radians) < 1e-9) {
          if (tag) tag.remove();
          return;
        }
        if (!tag) {
          tag = item.tags.add();
          tag.name = 'BBAccumRotation';
        }
        tag.value = String(radians);
      } catch (e2) { /* the tag only affects the Transform panel display */ }
    }

    function normalizeAngle(angle) {
      var a = angle % 360;
      if (a > 180) a -= 360;
      if (a <= -180) a += 360;
      return a;
    }

    // ---- Justification without moving point text ----------------------------
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

      if (range) setJustification(range, value);
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

    // ---- Baseline: first-line baselines of horizontal point text on one height --------
    function baseline(sel, o) {
      var list = objects(sel);
      if (list === null) return 'err|textedit';
      var texts = [];
      var others = [];
      var skipped = 0;
      var i;
      for (i = 0; i < list.length; i++) {
        var it = list[i];
        if (it.typename === 'TextFrame') {
          if (it.kind == TextType.POINTTEXT && it.orientation == TextOrientation.HORIZONTAL) texts.push(it);
          else skipped++;
        } else if (o.others) {
          others.push(it);
        }
      }
      if (!texts.length) return 'err|nopoint';
      if (texts.length + others.length < 2) return 'err|few|2';

      // the anchor of point text sits on its first baseline
      var target = texts[0].anchor[1];
      if (o.reference === 'left') {
        var minLeft = Infinity;
        for (i = 0; i < texts.length; i++) {
          var left = texts[i].geometricBounds[0];
          if (left < minLeft) {
            minLeft = left;
            target = texts[i].anchor[1];
          }
        }
      } else {
        var sum = 0;
        for (i = 0; i < texts.length; i++) {
          var y = texts[i].anchor[1];
          if (o.reference === 'top' && y > target) target = y;
          if (o.reference === 'bottom' && y < target) target = y;
          sum += y;
        }
        if (o.reference === 'average') target = sum / texts.length;
      }

      var patterns = preference('transformPatterns', true);
      for (i = 0; i < texts.length; i++) move(texts[i], 0, target - texts[i].anchor[1], patterns);
      for (i = 0; i < others.length; i++) move(others[i], 0, target - boundsOf(others[i], o)[3], patterns);
      return 'ok|base|' + texts.length + '|' + others.length + '|' + skipped;
    }

    // ---- Word spacing: tracking on the space characters only ----------------
    function wordSpace(sel, o) {
      var ranges = [];
      var i;
      if (sel && sel.typename === 'TextRange') {
        ranges.push(sel.length > 0 ? sel : sel.story.textRange);
      } else {
        var frames = [];
        for (i = 0; sel && i < sel.length; i++) collectText(sel[i], frames);
        for (i = 0; i < frames.length; i++) ranges.push(frames[i].textRange);
      }
      if (!ranges.length) return 'err|notext';

      var count = 0;
      var last = null;
      for (i = 0; i < ranges.length; i++) {
        var range = ranges[i];
        var text = range.contents;
        var chars = range.characters;
        // Without surrogate pairs the string index equals the character index (only spaces are touched).
        var fast = !hasSurrogates(text);
        var total = fast ? text.length : chars.length;
        for (var k = 0; k < total; k++) {
          var c = fast ? text.charAt(k) : chars[k].contents;
          if (c !== ' ' && c !== NBSP && c !== IDEOGRAPHIC_SPACE) continue;
          var attributes = chars[k].characterAttributes;
          var value = o.mode === 'add' ? attributes.tracking + o.value : o.value;
          value = Math.max(-1000, Math.min(10000, Math.round(value)));
          attributes.tracking = value;
          if (last === null) last = value;
          count++;
        }
      }
      return 'ok|word|' + count + '|' + (last === null ? '' : last);
    }

    function hasSurrogates(text) {
      for (var k = 0; k < text.length; k++) {
        var code = text.charCodeAt(k);
        if (code >= 0xD800 && code <= 0xDFFF) return true;
      }
      return false;
    }

    // ---- Artboards and artwork ---------------------------------------------
    // Artboard rectangles and object bounds must be in the same (document) coordinates.
    function inDocumentCoordinates(work) {
      var system = app.coordinateSystem;
      app.coordinateSystem = CoordinateSystem.DOCUMENTCOORDINATESYSTEM;
      try {
        return work();
      } finally {
        app.coordinateSystem = system;
      }
    }

    // Number the artboards in reading order (top-left first), lay them out on a grid and move their artwork.
    function arrange(o) {
      var doc = app.activeDocument;
      var boards = doc.artboards;
      var n = boards.length;
      var saved = [];
      var rects = [];
      var i;
      for (i = 0; i < n; i++) {
        saved.push(readBoard(boards[i]));
        rects.push(saved[i].rect);
      }
      var rows = readingRows(rects);
      var order = [];
      for (i = 0; i < rows.length; i++) order = order.concat(rows[i]);
      if (o.columns > 0) {
        rows = [];
        for (i = 0; i < order.length; i += o.columns) rows.push(order.slice(i, i + o.columns));
      }
      var target = gridRects(rows, rects, o.gap);
      var columns = 0;
      for (i = 0; i < rows.length; i++) columns = Math.max(columns, rows[i].length);
      var active = boards.getActiveArtboardIndex();

      // artboards first: if one lands outside the canvas, put them all back and stop
      try {
        for (i = 0; i < n; i++) boards[i].artboardRect = target[order[i]];
      } catch (e) {
        for (i = 0; i < n; i++) {
          try {
            boards[i].artboardRect = saved[i].rect;
          } catch (e2) { /* keep going */ }
        }
        return 'err|canvas';
      }
      for (i = 0; i < n; i++) boards[i].name = 'coc-' + i; // unique names on the way
      for (i = 0; i < n; i++) writeBoard(boards[i], saved[order[i]]);
      for (i = 0; i < n; i++) {
        if (order[i] === active) boards.setActiveArtboardIndex(i);
      }

      // then the artwork on each artboard, with locked and hidden things opened up for a moment
      var state = { layers: [], items: [], locked: 0 };
      var failed = 0;
      try {
        openUp(doc, state);
        var items = topItems(doc.layers, []);
        var patterns = preference('transformPatterns', true);
        for (i = 0; i < items.length; i++) {
          var owner = mostOverlap(boundsOf(items[i], { visible: true, glyph: false }), rects);
          if (owner < 0) continue;
          try {
            move(items[i], target[owner][0] - rects[owner][0], target[owner][1] - rects[owner][1], patterns);
          } catch (e3) {
            failed++;
          }
        }
      } finally {
        closeUp(state);
      }
      return 'ok|arrange|' + n + '|' + rows.length + '|' + columns + '|' + state.locked + '|' + failed;
    }

    function readBoard(board) {
      var r = board.artboardRect;
      var data = { rect: [r[0], r[1], r[2], r[3]], name: board.name, extra: {} };
      var keys = ['rulerOrigin', 'rulerPAR', 'showCenter', 'showCrossHairs', 'showSafeAreas'];
      for (var k = 0; k < keys.length; k++) {
        try {
          data.extra[keys[k]] = board[keys[k]];
        } catch (e) { /* not in this version */ }
      }
      return data;
    }

    function writeBoard(board, data) {
      board.name = data.name;
      for (var key in data.extra) {
        if (!data.extra.hasOwnProperty(key)) continue;
        try {
          board[key] = data.extra[key];
        } catch (e) { /* not in this version */ }
      }
    }

    // Rows from the top, left to right inside a row. An artboard joins a row when it overlaps every artboard
    // already in it vertically by at least half of the smaller height.
    function readingRows(rects) {
      var byTop = [];
      var i;
      for (i = 0; i < rects.length; i++) byTop.push(i);
      byTop.sort(function (a, b) { return (rects[b][1] - rects[a][1]) || (rects[a][0] - rects[b][0]) || (a - b); });
      var rows = [];
      var row = null;
      for (i = 0; i < byTop.length; i++) {
        if (!row || !sharesRow(rects[byTop[i]], row, rects)) {
          row = [];
          rows.push(row);
        }
        row.push(byTop[i]);
      }
      for (i = 0; i < rows.length; i++) {
        rows[i].sort(function (a, b) { return (rects[a][0] - rects[b][0]) || (rects[b][1] - rects[a][1]) || (a - b); });
      }
      return rows;
    }

    function sharesRow(r, row, rects) {
      for (var k = 0; k < row.length; k++) {
        var m = rects[row[k]];
        var overlap = Math.min(r[1], m[1]) - Math.max(r[3], m[3]);
        if (overlap < 0.5 * Math.min(r[1] - r[3], m[1] - m[3])) return false;
      }
      return true;
    }

    // New rectangle for each artboard: columns as wide as their widest artboard, rows as tall as their tallest,
    // artboards in the top-left corner of their cell, starting at the top-left corner of the current layout.
    function gridRects(rows, rects, gap) {
      var colWidth = [];
      var rowHeight = [];
      var left = Infinity;
      var top = -Infinity;
      var i;
      var j;
      for (i = 0; i < rects.length; i++) {
        left = Math.min(left, rects[i][0]);
        top = Math.max(top, rects[i][1]);
      }
      for (i = 0; i < rows.length; i++) {
        rowHeight[i] = 0;
        for (j = 0; j < rows[i].length; j++) {
          var r = rects[rows[i][j]];
          colWidth[j] = Math.max(colWidth[j] || 0, r[2] - r[0]);
          rowHeight[i] = Math.max(rowHeight[i], r[1] - r[3]);
        }
      }
      var out = [];
      var y = top;
      for (i = 0; i < rows.length; i++) {
        var x = left;
        for (j = 0; j < rows[i].length; j++) {
          var src = rects[rows[i][j]];
          out[rows[i][j]] = [x, y, x + src[2] - src[0], y - (src[1] - src[3])];
          x += colWidth[j] + gap;
        }
        y -= rowHeight[i] + gap;
      }
      return out;
    }

    // Top-level objects of every layer and sublayer (groups count as one object).
    function topItems(layers, out) {
      for (var i = 0; i < layers.length; i++) {
        var items = layers[i].pageItems;
        for (var k = 0; k < items.length; k++) out.push(items[k]);
        topItems(layers[i].layers, out);
      }
      return out;
    }

    // Index of the rectangle the bounds overlap most, or -1. Lines on an artboard edge still count.
    function mostOverlap(b, rects) {
      var best = -1;
      var bestArea = 0;
      for (var i = 0; i < rects.length; i++) {
        var r = rects[i];
        var w = Math.min(b[2], r[2]) - Math.max(b[0], r[0]);
        var h = Math.min(b[1], r[1]) - Math.max(b[3], r[3]);
        if (w < 0 || h < 0) continue;
        var area = Math.max(w, 1e-3) * Math.max(h, 1e-3);
        if (area > bestArea) {
          bestArea = area;
          best = i;
        }
      }
      return best;
    }

    // Unlock and show every layer and object for a moment, noting each change; closeUp() puts it all back.
    function openUp(doc, state) {
      openLayers(doc.layers, state);
      var all = doc.pageItems;
      for (var i = 0; i < all.length; i++) {
        try {
          var item = all[i];
          var locked = item.locked;
          var hidden = item.hidden;
          if (!locked && !hidden) continue;
          state.items.push({ item: item, locked: locked, hidden: hidden });
          if (locked) item.locked = false;
          if (hidden) item.hidden = false;
          if (locked) state.locked++;
        } catch (e) { /* leave this one as it is */ }
      }
    }

    function openLayers(layers, state) {
      for (var i = 0; i < layers.length; i++) {
        var layer = layers[i];
        var locked = layer.locked;
        var hidden = !layer.visible;
        if (locked || hidden) state.layers.push({ layer: layer, locked: locked, hidden: hidden });
        if (locked) layer.locked = false;
        if (hidden) layer.visible = true;
        if (locked) state.locked++;
        openLayers(layer.layers, state);
      }
    }

    function closeUp(state) {
      var i;
      for (i = state.items.length - 1; i >= 0; i--) {
        var r = state.items[i];
        try {
          if (r.hidden) r.item.hidden = true;
          if (r.locked) r.item.locked = true;
        } catch (e) { /* removed meanwhile */ }
      }
      for (i = state.layers.length - 1; i >= 0; i--) {
        var l = state.layers[i];
        try {
          if (l.hidden) l.layer.visible = false;
          if (l.locked) l.layer.locked = true;
        } catch (e2) { /* removed meanwhile */ }
      }
    }

    // Artboard names 1, 2, 3 ... in the Artboards panel order ('01' ... with pad).
    function renameBoards(o) {
      var boards = app.activeDocument.artboards;
      var n = boards.length;
      var digits = o.pad ? Math.max(2, String(n).length) : 1;
      var i;
      for (i = 0; i < n; i++) boards[i].name = 'coc-' + i; // unique names on the way
      for (i = 0; i < n; i++) boards[i].name = padNumber(i + 1, digits);
      return 'ok|rename|' + n + '|' + padNumber(1, digits) + '|' + padNumber(n, digits);
    }

    function padNumber(value, digits) {
      var text = String(value);
      while (text.length < digits) text = '0' + text;
      return text;
    }

    // Clip only the objects that stick out of the artboards they touch, each in its own clipping group
    // at its own place in the stacking order. Objects on several artboards keep what is on any of them.
    function trim() {
      var doc = app.activeDocument;
      var rects = [];
      var i;
      for (i = 0; i < doc.artboards.length; i++) {
        var r = doc.artboards[i].artboardRect;
        rects.push([r[0], r[1], r[2], r[3]]);
      }
      var items = topItems(doc.layers, []);
      var clipped = 0;
      var skipped = 0;
      var outside = 0;
      var failed = 0;
      for (i = 0; i < items.length; i++) {
        var item = items[i];
        if (item.typename === 'PathItem' && item.guides) continue;
        var b = boundsOf(item, { visible: true, glyph: false });
        var hits = touching(b, rects);
        if (!hits.length) {
          outside++;
          continue;
        }
        if (covered(b, hits, rects)) continue;
        if (item.locked || item.hidden || !item.editable) {
          skipped++;
          continue;
        }
        try {
          clipTo(item, hits, rects);
          clipped++;
        } catch (e) {
          failed++;
        }
      }
      return 'ok|trim|' + clipped + '|' + skipped + '|' + outside + '|' + failed;
    }

    function touching(b, rects) {
      var out = [];
      for (var i = 0; i < rects.length; i++) {
        var r = rects[i];
        if (Math.min(b[2], r[2]) - Math.max(b[0], r[0]) > 0 && Math.min(b[1], r[1]) - Math.max(b[3], r[3]) > 0) out.push(i);
      }
      return out;
    }

    // Is every part of the bounds inside one of the rectangles? (slivers under 0.01 pt do not count)
    function covered(b, hits, rects) {
      var eps = 0.01;
      var xs = [b[0], b[2]];
      var ys = [b[3], b[1]];
      var i;
      for (i = 0; i < hits.length; i++) {
        var r = rects[hits[i]];
        if (r[0] > b[0] && r[0] < b[2]) xs.push(r[0]);
        if (r[2] > b[0] && r[2] < b[2]) xs.push(r[2]);
        if (r[3] > b[3] && r[3] < b[1]) ys.push(r[3]);
        if (r[1] > b[3] && r[1] < b[1]) ys.push(r[1]);
      }
      xs.sort(function (p, q) { return p - q; });
      ys.sort(function (p, q) { return p - q; });
      for (i = 1; i < xs.length; i++) {
        if (xs[i] - xs[i - 1] <= eps) continue;
        for (var j = 1; j < ys.length; j++) {
          if (ys[j] - ys[j - 1] <= eps) continue;
          var x = (xs[i] + xs[i - 1]) / 2;
          var y = (ys[j] + ys[j - 1]) / 2;
          var inside = false;
          for (var k = 0; k < hits.length && !inside; k++) {
            var c = rects[hits[k]];
            inside = x >= c[0] - eps && x <= c[2] + eps && y >= c[3] - eps && y <= c[1] + eps;
          }
          if (!inside) return false;
        }
      }
      return true;
    }

    function clipTo(item, hits, rects) {
      var group = item.parent.groupItems.add();
      group.move(item, ElementPlacement.PLACEBEFORE);
      var mask = hits.length === 1 ? group : group.compoundPathItems.add();
      for (var i = 0; i < hits.length; i++) {
        var r = rects[hits[i]];
        var rect = mask.pathItems.rectangle(r[1], r[0], r[2] - r[0], r[1] - r[3]);
        rect.filled = false;
        rect.stroked = false;
      }
      item.move(group, ElementPlacement.PLACEATEND);
      group.clipped = true;
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
  function addTab(tabs, title) {
    var tab = tabs.add('tab', undefined, title);
    tab.orientation = 'column';
    tab.alignChildren = ['fill', 'top'];
    tab.spacing = 6;
    tab.margins = [10, 12, 10, 10];
    return tab;
  }

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
