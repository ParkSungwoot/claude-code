'use strict';
// Simulate After Effects reading a .jsx WITHOUT the BOM using a legacy code page:
// the script must still parse (no syntax error) and show the escaped fallback message.
// With correct UTF-8 decoding the canary must pass and the script must go on to use `app`.
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const iconv = require('iconv-lite');

const KOREAN_WORD = String.fromCharCode(0xC778, 0xCF54, 0xB529); // "인코딩"

// No arguments: check every .jsx in ../scripts
function defaultFiles() {
  const dir = path.join(__dirname, '..', 'scripts');
  return fs.readdirSync(dir).sort().filter((name) => /\.jsx$/.test(name)).map((name) => path.join(dir, name));
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
      app: { get project() { throw new Error('should not reach app'); } },
      Panel: function Panel() {},
      Window: function () { throw new Error('should not reach app'); },
    });
    let result;
    try {
      try {
        vm.runInContext(src, ctx, { filename: file });
      } catch (e) {
        // with the right encoding the panel goes on to build its window
        if (!/should not reach app/.test(e.message)) throw e;
        alerts.push(e.message);
      }
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
    console.log(`${path.basename(file).padEnd(28)} ${enc.padEnd(13)} ${result}`);
  }
}
process.exit(bad ? 1 : 0);
