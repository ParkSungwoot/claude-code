'use strict';
// Simulate Illustrator reading a .jsx WITHOUT the BOM using a legacy code page:
// the script must still parse (no syntax error) and show the escaped fallback message.
// With correct UTF-8 decoding the canary must pass and the script must go on to use `app`.
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const iconv = require('iconv-lite');

const KOREAN_WORD = String.fromCharCode(0xC778, 0xCF54, 0xB529); // "인코딩"

// No arguments: check every .jsx in ../scripts and ../template
function defaultFiles() {
  const base = require('path').join(__dirname, '..');
  const out = [];
  for (const dir of ['scripts', 'template']) {
    for (const name of fs.readdirSync(require('path').join(base, dir)).sort()) {
      if (/\.jsx$/.test(name)) out.push(require('path').join(base, dir, name));
    }
  }
  return out;
}

let bad = 0;
const files = process.argv.length > 2 ? process.argv.slice(2) : defaultFiles();
for (const file of files) {
  const bytes = fs.readFileSync(file).subarray(3); // drop BOM
  for (const enc of ['cp949', 'shift_jis', 'macroman', 'windows-1252', 'utf8']) {
    const src = iconv.decode(bytes, enc);
    const alerts = [];
    const ctx = vm.createContext({
      alert: (m) => alerts.push(String(m)),
      $: { global: {} },
      app: { get documents() { throw new Error('should not reach app'); } },
      Window: function () { throw new Error('should not reach app'); },
    });
    let result;
    try {
      vm.runInContext(src, ctx, { filename: file });
      if (enc === 'utf8') {
        result = (alerts.length === 1 && alerts[0].indexOf('should not reach app') !== -1)
          ? 'ok (canary passes, script continues)' : 'UNEXPECTED ' + JSON.stringify(alerts);
      } else {
        result = (alerts.length === 1 && alerts[0].indexOf('wrong text encoding') !== -1 && alerts[0].indexOf(KOREAN_WORD) !== -1)
          ? 'ok (fallback message, Korean intact)' : 'UNEXPECTED ' + JSON.stringify(alerts);
      }
    } catch (e) {
      result = 'THREW ' + e.message;
    }
    if (!/^ok/.test(result)) bad++;
    console.log(`${path.basename(file).padEnd(22)} ${enc.padEnd(13)} ${result}`);
  }
}
process.exit(bad ? 1 : 0);
