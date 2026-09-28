//@target illustrator
/*
 * ============================================================================
 *  대지 내보내기  (ExportArtboards.jsx)  v1.0.0
 * ============================================================================
 *  대지를 하나씩 PNG · JPG · SVG · PDF 파일로 저장합니다.
 *
 *  - 대상: 현재 문서 또는 열린 문서 모두 / 모든 대지 · 현재 대지 · 범위(1-3, 5)
 *  - PNG: 해상도(ppi), 투명 배경      JPG: 해상도(ppi), 품질(0~100)
 *  - SVG: 텍스트를 윤곽선으로 변환     PDF: PDF 사전 설정 선택 (CC 2018 이상)
 *  - 파일 이름 규칙: {doc} 문서 이름, {artboard} 대지 이름, {n} 대지 번호({nn} → 01)
 *  - 같은 이름의 파일이 있으면 덮어쓰거나 이름 뒤에 _2, _3 … 을 붙입니다.
 *
 *  실행 : 파일 > 스크립트 > 기타 스크립트... 에서 이 파일 선택
 *  지원 : Adobe Illustrator CC 2017 이상 (PDF 는 CC 2018 이상), Windows / macOS
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

  var SCRIPT_TITLE = '대지 내보내기';
  var SETTINGS_NAME = 'ExportArtboards';
  var LABEL_WIDTH = 70;
  var MAX_PPI = 558; // PNG/JPG 내보내기 배율의 최대치 776.19% 를 ppi 로 바꾼 값 (72 × 7.7619)

  var FORMATS = [
    { key: 'png', label: 'PNG', ext: 'png' },
    { key: 'jpg', label: 'JPG', ext: 'jpg' },
    { key: 'svg', label: 'SVG', ext: 'svg' },
    { key: 'pdf', label: 'PDF', ext: 'pdf', minVersion: 22 } // 'Export for Screens' 스크립트 기능 필요 (CC 2018)
  ];

  // 처음 실행할 때의 기본값. 이후에는 마지막으로 쓴 값을 기억합니다.
  var DEFAULTS = {
    docScope: 'current',   // current | all
    boardScope: 'all',     // all | active | range
    range: '1-3',
    format: 'png',
    ppi: '150',
    transparent: true,
    quality: 80,
    outlineText: false,
    pdfPreset: '',
    pattern: '{doc}_{artboard}',
    saveBeside: true,
    folder: '',
    overwrite: false,
    openFolder: true
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
    var job = showDialog(loadSettings(SETTINGS_NAME, DEFAULTS));
    if (!job) return; // 취소
    showReport(runExport(job), job);
  }

  // ==========================================================================
  //  대화상자
  // ==========================================================================
  function showDialog(s) {
    var doc = app.activeDocument;
    var docCount = app.documents.length;
    var formats = availableFormats();
    var presets = pdfPresets();
    var chosenFolder = existingFolder(s.folder) || documentFolder(doc) || Folder.desktop;
    var job = null;

    var win = new Window('dialog', SCRIPT_TITLE);
    win.orientation = 'column';
    win.alignChildren = ['fill', 'top'];
    win.spacing = 10;
    win.margins = 16;

    // ---- 대상 -------------------------------------------------------------
    var pSource = addPanel(win, '대상');
    var gDocs = addRow(pSource);
    addLabel(gDocs, '문서:', LABEL_WIDTH);
    var rbCurrentDoc = gDocs.add('radiobutton', undefined, '현재 문서');
    var rbAllDocs = gDocs.add('radiobutton', undefined, '열린 문서 모두 (' + docCount + '개)');
    rbAllDocs.enabled = docCount > 1;
    rbAllDocs.value = (s.docScope === 'all' && docCount > 1);
    rbCurrentDoc.value = !rbAllDocs.value;

    var gBoards = addRow(pSource);
    addLabel(gBoards, '대지:', LABEL_WIDTH);
    var rbAllBoards = gBoards.add('radiobutton', undefined, '모든 대지');
    var rbActiveBoard = gBoards.add('radiobutton', undefined, '현재 대지만');
    var rbRange = gBoards.add('radiobutton', undefined, '범위:');
    var etRange = gBoards.add('edittext', undefined, s.range);
    etRange.characters = 10;
    rbActiveBoard.value = (s.boardScope === 'active');
    rbRange.value = (s.boardScope === 'range');
    rbAllBoards.value = !rbActiveBoard.value && !rbRange.value;
    var gRangeHint = addRow(pSource);
    addLabel(gRangeHint, '', LABEL_WIDTH);
    gRangeHint.add('statictext', undefined, '범위 예: 1-3, 5   (대지 패널의 번호)');

    // ---- 형식 -------------------------------------------------------------
    var pFormat = addPanel(win, '형식');
    var gFormat = addRow(pFormat);
    addLabel(gFormat, '형식:', LABEL_WIDTH);
    var ddFormat = gFormat.add('dropdownlist', undefined, formatLabels(formats));
    ddFormat.selection = formatIndex(formats, s.format);

    var gPpi = addRow(pFormat);
    addLabel(gPpi, '해상도:', LABEL_WIDTH);
    var etPpi = gPpi.add('edittext', undefined, s.ppi);
    etPpi.characters = 5;
    gPpi.add('statictext', undefined, 'ppi   (72 = 원래 크기, 150, 300 ... 최대 ' + MAX_PPI + ')');

    // 형식마다 다른 옵션을 같은 자리에 겹쳐 두고, 고른 형식의 것만 보여 줍니다.
    var stack = pFormat.add('group');
    stack.orientation = 'stack';
    stack.alignment = ['fill', 'top'];
    stack.alignChildren = ['left', 'top'];

    var gPng = addRow(stack);
    addLabel(gPng, '', LABEL_WIDTH);
    var cbTransparent = gPng.add('checkbox', undefined, '투명 배경');
    cbTransparent.value = s.transparent;

    var gJpg = addRow(stack);
    addLabel(gJpg, '품질:', LABEL_WIDTH);
    var slQuality = gJpg.add('slider', undefined, clamp(s.quality, 0, 100), 0, 100);
    slQuality.preferredSize.width = 200;
    var stQuality = gJpg.add('statictext', undefined, String(Math.round(slQuality.value)));
    stQuality.preferredSize.width = 30;

    var gSvg = addRow(stack);
    addLabel(gSvg, '', LABEL_WIDTH);
    var cbOutline = gSvg.add('checkbox', undefined, '텍스트를 윤곽선으로 변환 (글꼴이 없어도 똑같이 보임)');
    cbOutline.value = s.outlineText;

    var gPdf = addRow(stack);
    addLabel(gPdf, '사전 설정:', LABEL_WIDTH);
    var ddPreset = gPdf.add('dropdownlist', undefined, presets.length ? presets : ['(기본값)']);
    ddPreset.selection = presetIndex(presets, s.pdfPreset);

    // ---- 파일 이름 --------------------------------------------------------
    var pName = addPanel(win, '파일 이름');
    var gPattern = addRow(pName);
    addLabel(gPattern, '이름 규칙:', LABEL_WIDTH);
    var etPattern = gPattern.add('edittext', undefined, s.pattern);
    etPattern.characters = 30;
    var gTokens = addRow(pName);
    addLabel(gTokens, '', LABEL_WIDTH);
    gTokens.add('statictext', undefined, '{doc} 문서 이름   {artboard} 대지 이름   {n} 번호 ({nn} → 01)');
    var gExample = addRow(pName);
    addLabel(gExample, '', LABEL_WIDTH);
    var stExample = gExample.add('statictext', undefined, '');
    stExample.preferredSize.width = 360;

    // ---- 저장 위치 --------------------------------------------------------
    var pDest = addPanel(win, '저장 위치');
    var gDestMode = addRow(pDest);
    var rbBeside = gDestMode.add('radiobutton', undefined, '문서와 같은 폴더');
    var rbFolder = gDestMode.add('radiobutton', undefined, '아래 폴더');
    rbBeside.value = s.saveBeside;
    rbFolder.value = !s.saveBeside;
    var gFolder = addRow(pDest);
    var stFolder = gFolder.add('statictext', undefined, '', { truncate: 'middle' });
    stFolder.preferredSize.width = 330;
    var btnBrowse = gFolder.add('button', undefined, '폴더 선택...');
    pDest.add('statictext', undefined, '저장한 적 없는 문서는 "문서와 같은 폴더"를 골라도 위 폴더에 저장됩니다.');
    var gFlags = addRow(pDest);
    var cbOverwrite = gFlags.add('checkbox', undefined, '같은 이름의 파일 덮어쓰기');
    cbOverwrite.value = s.overwrite;
    var cbOpenFolder = gFlags.add('checkbox', undefined, '끝나면 폴더 열기');
    cbOpenFolder.value = s.openFolder;

    var stStatus = win.add('statictext', undefined, '');
    stStatus.preferredSize.width = 440;

    var buttons = addButtons(win, '내보내기');

    // ---- 동작 연결 ---------------------------------------------------------
    ddFormat.onChange = update;
    slQuality.onChanging = function () {
      stQuality.text = String(Math.round(slQuality.value));
    };
    slQuality.onChange = slQuality.onChanging;
    rbCurrentDoc.onClick = update;
    rbAllDocs.onClick = update;
    rbAllBoards.onClick = update;
    rbActiveBoard.onClick = update;
    rbRange.onClick = function () {
      update();
      etRange.active = true;
    };
    etRange.onChanging = update;
    etPpi.onChanging = update;
    etPattern.onChanging = update;
    rbBeside.onClick = update;
    rbFolder.onClick = update;
    btnBrowse.onClick = function () {
      var start = (chosenFolder && chosenFolder.exists) ? chosenFolder : Folder.desktop;
      var picked = start.selectDlg('내보낸 파일을 저장할 폴더를 선택하세요.');
      if (!picked) return;
      chosenFolder = picked;
      rbFolder.value = true;
      rbBeside.value = false;
      update();
    };

    buttons.ok.onClick = function () {
      var o = readOptions();
      if (o.error) {
        stStatus.text = '확인 필요: ' + o.error;
        return;
      }
      job = o;
      saveSettings(SETTINGS_NAME, {
        docScope: rbAllDocs.value ? 'all' : 'current',
        boardScope: o.boardScope,
        range: etRange.text,
        format: o.format.key,
        ppi: etPpi.text,
        transparent: cbTransparent.value,
        quality: o.quality,
        outlineText: cbOutline.value,
        pdfPreset: o.pdfPreset,
        pattern: etPattern.text,
        saveBeside: rbBeside.value,
        folder: chosenFolder ? chosenFolder.fullName : '',
        overwrite: cbOverwrite.value,
        openFolder: cbOpenFolder.value
      });
      win.close(1);
    };
    buttons.cancel.onClick = function () {
      win.close(2);
    };

    update();
    win.center();
    return win.show() === 1 ? job : null;

    // ---- 내부 함수 ---------------------------------------------------------
    function currentFormat() {
      return formats[ddFormat.selection ? ddFormat.selection.index : 0];
    }

    function readOptions() {
      var format = currentFormat();
      var o = {
        format: format,
        boardScope: rbRange.value ? 'range' : (rbActiveBoard.value ? 'active' : 'all'),
        ppi: parseNumber(etPpi.text),
        transparent: cbTransparent.value,
        quality: Math.round(slQuality.value),
        outlineText: cbOutline.value,
        pdfPreset: (presets.length && ddPreset.selection) ? ddPreset.selection.text : '',
        pattern: trim(etPattern.text),
        saveBeside: rbBeside.value,
        folder: chosenFolder,
        overwrite: cbOverwrite.value,
        openFolder: cbOpenFolder.value,
        targets: [],
        total: 0,
        error: ''
      };

      var docs = rbAllDocs.value ? openDocuments() : [doc];
      for (var d = 0; d < docs.length; d++) {
        var indices = artboardIndices(docs[d], o.boardScope, etRange.text);
        if (indices === null) {
          o.error = '범위를 "1-3, 5" 처럼 입력해 주세요.';
          return o;
        }
        if (indices.length) {
          o.targets.push({ doc: docs[d], indices: indices });
          o.total += indices.length;
        }
      }

      var raster = (format.key === 'png' || format.key === 'jpg');
      if (raster && (isNaN(o.ppi) || o.ppi < 1 || o.ppi > MAX_PPI)) {
        o.error = '해상도는 1~' + MAX_PPI + ' 사이의 숫자로 입력해 주세요.';
      } else if (o.pattern === '') {
        o.error = '파일 이름 규칙을 입력해 주세요.';
      } else if (!o.total) {
        o.error = '내보낼 대지가 없습니다. 범위를 확인해 주세요.';
      } else if (!o.saveBeside && !(o.folder && o.folder.exists)) {
        o.error = '저장할 폴더를 선택해 주세요.';
      }
      return o;
    }

    function update() {
      var o = readOptions();
      var key = o.format.key;
      gPng.visible = (key === 'png');
      gJpg.visible = (key === 'jpg');
      gSvg.visible = (key === 'svg');
      gPdf.visible = (key === 'pdf');
      gPpi.enabled = (key === 'png' || key === 'jpg');
      etRange.enabled = rbRange.value;
      stFolder.text = chosenFolder ? chosenFolder.fsName : '(폴더를 선택하세요)';

      stExample.text = '';
      if (o.pattern !== '' && o.targets.length) {
        var first = o.targets[0];
        stExample.text = '예: ' + fileBaseName(o.pattern, first.doc, first.indices[0]) + '.' + o.format.ext;
      }
      if (o.error) {
        stStatus.text = '확인 필요: ' + o.error;
        buttons.ok.enabled = false;
      } else {
        stStatus.text = '대지 ' + o.total + '개를 ' + o.format.label + ' 파일로 내보냅니다.';
        buttons.ok.enabled = true;
      }
    }
  }

  // ==========================================================================
  //  내보내기
  // ==========================================================================
  function runExport(o) {
    var report = { exported: 0, failed: [], folders: [] };
    var progress = createProgress(o.total);
    var originalDoc = app.activeDocument;
    var oldLevel = app.userInteractionLevel;
    var used = {};
    var done = 0;
    app.userInteractionLevel = UserInteractionLevel.DONTDISPLAYALERTS; // 내보내는 동안 경고창 끄기
    try {
      for (var d = 0; d < o.targets.length; d++) {
        var doc = o.targets[d].doc;
        var indices = o.targets[d].indices;
        if (o.targets.length > 1) app.activeDocument = doc;
        var folder = (o.saveBeside && documentFolder(doc)) || o.folder;
        if (!folder.exists) folder.create();
        rememberFolder(report.folders, folder);

        var activeIndex = doc.artboards.getActiveArtboardIndex();
        for (var k = 0; k < indices.length; k++) {
          var file = uniqueFile(folder, fileBaseName(o.pattern, doc, indices[k]), o.format.ext, o.overwrite, used);
          progress.step(done, file.displayName);
          try {
            exportArtboard(doc, indices[k], o, file);
            report.exported++;
          } catch (e) {
            report.failed.push(file.displayName + ' : ' + e.message);
          }
          done++;
        }
        try {
          doc.artboards.setActiveArtboardIndex(activeIndex); // 원래 선택돼 있던 대지로
        } catch (e) { /* 무시 */ }
      }
    } finally {
      app.userInteractionLevel = oldLevel;
      progress.close();
      try {
        app.activeDocument = originalDoc;
      } catch (e) { /* 무시 */ }
    }
    return report;
  }

  // 대지 하나를 임시 폴더에 내보낸 뒤, 원하는 이름으로 저장 위치에 복사합니다.
  // (일러스트레이터가 파일 이름 뒤에 대지 이름 등을 덧붙이는 경우가 있어서 이렇게 합니다)
  function exportArtboard(doc, index, o, destination) {
    var temp = createTempFolder();
    try {
      var key = o.format.key;
      if (key === 'pdf') {
        var item = new ExportForScreensItemToExport();
        item.artboards = String(index + 1);
        item.document = false;
        var pdfOptions = new ExportForScreensPDFOptions();
        if (o.pdfPreset) pdfOptions.pdfPreset = o.pdfPreset;
        doc.exportForScreens(temp, ExportForScreensType.SE_PDF, pdfOptions, item, '');
      } else {
        doc.artboards.setActiveArtboardIndex(index);
        var out = new File(temp.fullName + '/artboard.' + o.format.ext);
        var scale = o.ppi / 72 * 100; // 100% = 72ppi
        if (key === 'png') {
          var png = new ExportOptionsPNG24();
          png.artBoardClipping = true;
          png.antiAliasing = true;
          png.transparency = o.transparent;
          png.horizontalScale = scale;
          png.verticalScale = scale;
          doc.exportFile(out, ExportType.PNG24, png);
        } else if (key === 'jpg') {
          var jpg = new ExportOptionsJPEG();
          jpg.artBoardClipping = true;
          jpg.antiAliasing = true;
          jpg.qualitySetting = o.quality;
          jpg.horizontalScale = scale;
          jpg.verticalScale = scale;
          doc.exportFile(out, ExportType.JPEG, jpg);
        } else {
          var svg = new ExportOptionsWebOptimizedSVG();
          svg.saveMultipleArtboards = true;
          svg.artboardRange = String(index + 1);
          svg.fontType = o.outlineText ? SVGFontType.OUTLINEFONT : SVGFontType.SVGFONT;
          svg.rasterImageLocation = RasterImageLocation.EMBED;
          doc.exportFile(out, ExportType.WOSVG, svg);
        }
      }

      var produced = pickExported(findFiles(temp, o.format.ext), doc.artboards[index].name);
      if (!produced) throw new Error('내보낸 파일이 만들어지지 않았습니다.');
      if (destination.exists && !destination.remove()) throw new Error('기존 파일을 지울 수 없습니다. (다른 프로그램에서 열려 있는지 확인)');
      if (!produced.copy(destination.fullName)) throw new Error('저장 위치에 파일을 쓸 수 없습니다.');
    } finally {
      removeFolder(temp);
    }
  }

  // 임시 폴더에 파일이 여러 개 생겼다면, 대지 이름이 들어간 것을 고릅니다.
  function pickExported(files, artboardName) {
    if (!files.length) return null;
    for (var i = 0; i < files.length; i++) {
      if (files[i].displayName.indexOf(artboardName) !== -1) return files[i];
    }
    return files[0];
  }

  function createProgress(total) {
    var win = new Window('palette', SCRIPT_TITLE);
    win.orientation = 'column';
    win.alignChildren = ['fill', 'top'];
    win.margins = 16;
    var label = win.add('statictext', undefined, '준비 중...');
    label.preferredSize.width = 360;
    var bar = win.add('progressbar', undefined, 0, total);
    bar.preferredSize.width = 360;
    win.show();
    return {
      step: function (index, name) {
        label.text = '(' + (index + 1) + '/' + total + ')  ' + name;
        bar.value = index;
        win.update();
      },
      close: function () {
        win.close();
      }
    };
  }

  function showReport(report, o) {
    var lines = [];
    if (report.exported) lines.push(report.exported + '개 파일을 내보냈습니다.');
    if (report.failed.length) {
      lines.push(report.failed.length + '개는 내보내지 못했습니다.');
      lines.push(report.failed.slice(0, 5).join('\n') + (report.failed.length > 5 ? '\n...' : ''));
    }
    for (var i = 0; i < report.folders.length && i < 3; i++) lines.push('저장 위치: ' + report.folders[i].fsName);
    if (report.folders.length > 3) lines.push('외 ' + (report.folders.length - 3) + '곳');
    alert(lines.join('\n'), SCRIPT_TITLE, report.failed.length > 0);
    if (o.openFolder && report.exported && report.folders.length) report.folders[0].execute();
  }

  // ==========================================================================
  //  대지 · 파일 이름
  // ==========================================================================
  function artboardIndices(doc, scope, rangeText) {
    var count = doc.artboards.length;
    if (scope === 'active') return [doc.artboards.getActiveArtboardIndex()];
    if (scope === 'range') return parseRange(rangeText, count);
    var all = [];
    for (var i = 0; i < count; i++) all.push(i);
    return all;
  }

  // "1-3, 5" → [0, 1, 2, 4] (0부터 시작하는 번호). 형식이 틀리면 null, 문서에 없는 번호는 뺍니다.
  function parseRange(text, count) {
    var parts = String(text).split(',');
    var seen = {};
    var out = [];
    var hasPart = false;
    for (var i = 0; i < parts.length; i++) {
      var part = trim(parts[i]);
      if (part === '') continue;
      hasPart = true;
      var from, to;
      var m = part.match(/^(\d+)\s*[-~]\s*(\d+)$/);
      if (m) {
        from = parseInt(m[1], 10);
        to = parseInt(m[2], 10);
      } else if (/^\d+$/.test(part)) {
        from = to = parseInt(part, 10);
      } else {
        return null;
      }
      if (from > to) {
        var swap = from;
        from = to;
        to = swap;
      }
      for (var n = Math.max(from, 1); n <= Math.min(to, count); n++) {
        if (!seen[n]) {
          seen[n] = true;
          out.push(n - 1);
        }
      }
    }
    if (!hasPart) return null;
    out.sort(function (a, b) { return a - b; });
    return out;
  }

  function fileBaseName(pattern, doc, index) {
    var docName = doc.name.replace(/\.[^.]*$/, '');
    var boardName = doc.artboards[index].name;
    var name = pattern.replace(/\{(doc|artboard|n+)\}/g, function (all, key) {
      if (key === 'doc') return docName;
      if (key === 'artboard') return boardName;
      return padNumber(index + 1, key.length);
    });
    return sanitizeFileName(name);
  }

  // 파일 이름에 쓸 수 없는 글자(\ / : * ? " < > |)는 _ 로 바꿉니다.
  function sanitizeFileName(name) {
    var s = String(name).replace(/[\\\/:*?"<>|\u0000-\u001F]/g, '_');
    s = s.replace(/^\s+/, '').replace(/[\s.]+$/, '');
    if (s === '') s = 'untitled';
    return s.length > 150 ? s.substring(0, 150) : s;
  }

  // 이번 실행에서 이미 쓴 이름이나(대소문자 무시), 덮어쓰기를 끈 상태에서 이미 있는 파일이면 _2, _3 ... 을 붙입니다.
  function uniqueFile(folder, base, ext, overwrite, used) {
    for (var k = 1; ; k++) {
      var file = childFile(folder, base + (k > 1 ? '_' + k : '') + '.' + ext);
      var key = file.fsName.toLowerCase();
      if (used[key] || (!overwrite && file.exists)) continue;
      used[key] = true;
      return file;
    }
  }

  // ==========================================================================
  //  파일 · 폴더 도우미
  // ==========================================================================
  function childFile(folder, name) {
    return new File(folder.fullName + '/' + File.encode(name));
  }

  function documentFolder(doc) {
    try {
      var file = doc.fullName;
      if (file && file.exists) return file.parent;
    } catch (e) { /* 저장한 적 없는 문서 */ }
    return null;
  }

  function existingFolder(path) {
    if (!path) return null;
    var folder = new Folder(path);
    return folder.exists ? folder : null;
  }

  function rememberFolder(list, folder) {
    for (var i = 0; i < list.length; i++) {
      if (list[i].fsName === folder.fsName) return;
    }
    list.push(folder);
  }

  function createTempFolder() {
    var folder = new Folder(Folder.temp.fullName + '/ai_export_' + new Date().getTime() + '_' + Math.floor(Math.random() * 100000));
    if (!folder.create()) throw new Error('임시 폴더를 만들 수 없습니다.');
    return folder;
  }

  function findFiles(folder, ext) {
    var found = [];
    var pattern = new RegExp('\\.' + ext + '$', 'i');
    var entries = folder.getFiles();
    for (var i = 0; i < entries.length; i++) {
      if (entries[i] instanceof Folder) found = found.concat(findFiles(entries[i], ext));
      else if (pattern.test(entries[i].displayName)) found.push(entries[i]);
    }
    return found;
  }

  function removeFolder(folder) {
    try {
      var entries = folder.getFiles();
      for (var i = 0; i < entries.length; i++) {
        if (entries[i] instanceof Folder) removeFolder(entries[i]);
        else entries[i].remove();
      }
      folder.remove();
    } catch (e) { /* 임시 폴더 정리 실패는 무시 */ }
  }

  function openDocuments() {
    var list = [];
    for (var i = 0; i < app.documents.length; i++) list.push(app.documents[i]);
    return list;
  }

  // ==========================================================================
  //  형식 · 사전 설정
  // ==========================================================================
  function availableFormats() {
    var version = parseInt(app.version, 10);
    var list = [];
    for (var i = 0; i < FORMATS.length; i++) {
      if (!FORMATS[i].minVersion || version >= FORMATS[i].minVersion) list.push(FORMATS[i]);
    }
    return list;
  }

  function formatLabels(formats) {
    var labels = [];
    for (var i = 0; i < formats.length; i++) labels.push(formats[i].label);
    return labels;
  }

  function formatIndex(formats, key) {
    for (var i = 0; i < formats.length; i++) {
      if (formats[i].key === key) return i;
    }
    return 0;
  }

  function pdfPresets() {
    var list = [];
    try {
      var names = app.PDFPresetsList;
      for (var i = 0; i < names.length; i++) list.push(names[i]);
    } catch (e) { /* 사전 설정 목록을 못 읽으면 기본값 사용 */ }
    return list;
  }

  function presetIndex(presets, saved) {
    var i;
    for (i = 0; i < presets.length; i++) {
      if (presets[i] === saved) return i;
    }
    for (i = 0; i < presets.length; i++) {
      if (/High Quality Print|고품질 인쇄/.test(presets[i])) return i;
    }
    return 0;
  }

  // ==========================================================================
  //  작은 도우미 함수
  // ==========================================================================
  function padNumber(num, width) {
    var s = String(Math.abs(num));
    while (s.length < width) s = '0' + s;
    return (num < 0 ? '-' : '') + s;
  }

  function parseNumber(text) {
    var t = trim(text).replace(',', '.');
    return /^[+-]?(\d+\.?\d*|\.\d+)$/.test(t) ? parseFloat(t) : NaN;
  }

  function trim(text) {
    return String(text).replace(/^\s+|\s+$/g, '');
  }

  function clamp(value, min, max) {
    var n = Number(value);
    if (isNaN(n)) return min;
    return Math.max(min, Math.min(max, n));
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
