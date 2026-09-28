'use strict';
// ES3 / ExtendScript lint for .jsx files: BOM, syntax (acorn ecmaVersion 3), ES5+ API usage,
// reserved words as property names, trailing commas / holes in arrays.
const fs = require('fs');
const acorn = require('acorn');
const walk = require('acorn-walk');

const RESERVED_ES3 = new Set(('break case catch continue default delete do else finally for function if in instanceof new ' +
  'return switch this throw try typeof var void while with abstract boolean byte char class const debugger double enum ' +
  'export extends final float goto implements import int interface long native package private protected public short ' +
  'static super synchronized throws transient volatile null true false').split(' '));
const ES5_MEMBERS = new Set(['forEach', 'map', 'filter', 'reduce', 'reduceRight', 'some', 'every', 'trim', 'trimLeft',
  'trimRight', 'trimStart', 'trimEnd', 'bind', 'toISOString', 'includes', 'startsWith', 'endsWith', 'padStart', 'padEnd',
  'repeat', 'findIndex']);
const ES5_STATIC = {
  Object: new Set(['keys', 'create', 'defineProperty', 'defineProperties', 'getPrototypeOf', 'getOwnPropertyNames',
    'assign', 'entries', 'values', 'freeze', 'seal']),
  Array: new Set(['isArray', 'from', 'of']),
  Date: new Set(['now']),
  Number: new Set(['isNaN', 'isFinite', 'isInteger', 'parseFloat', 'parseInt']),
};
const ES5_GLOBALS = new Set(['JSON', 'console', 'Promise', 'Map', 'Set', 'Symbol', 'Proxy', 'Reflect', 'globalThis']);


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

let failures = 0;
const files = process.argv.length > 2 ? process.argv.slice(2) : defaultFiles();
for (const file of files) {
  const problems = [];
  const buf = fs.readFileSync(file);
  if (!(buf[0] === 0xef && buf[1] === 0xbb && buf[2] === 0xbf)) problems.push('missing UTF-8 BOM');
  let src = buf.toString('utf8');
  if (src.charCodeAt(0) === 0xfeff) src = src.slice(1);
  if (/\r/.test(src)) problems.push('contains CR characters (use LF)');
  if (/[ \t]+$/m.test(src)) problems.push('trailing whitespace');
  if (/[\u0000-\u0009\u000B-\u001F\u007F-\u009F\u2028\u2029\uFEFF]/.test(src)) problems.push('raw control/invisible character in source');
  const fb = src.indexOf("alert('This script file was saved with the wrong text encoding.");
  if (fb < 0) problems.push('missing encoding fallback alert');
  else if (/[^\x00-\x7f]/.test(src.slice(fb, src.indexOf("');", fb)))) problems.push('encoding fallback message must be ASCII (use \\u escapes)');
  if (!/if \('가'\.length !== 1 \|\| '가'\.charCodeAt\(0\) !== 0xAC00\)/.test(src)) problems.push('missing encoding canary');

  let ast;
  try {
    ast = acorn.parse(src, { ecmaVersion: 3, locations: true, allowReserved: true });
  } catch (e) {
    problems.push('syntax (ES3): ' + e.message);
  }
  if (ast) {
    walk.full(ast, (node) => {
      const at = node.loc ? `line ${node.loc.start.line}` : '';
      if (node.type === 'MemberExpression' && !node.computed) {
        if (RESERVED_ES3.has(node.property.name)) problems.push(`${at}: reserved word as property .${node.property.name}`);
        if (ES5_MEMBERS.has(node.property.name)) problems.push(`${at}: ES5+ member .${node.property.name}`);
        if (node.object.type === 'Identifier' && ES5_STATIC[node.object.name] && ES5_STATIC[node.object.name].has(node.property.name)) {
          problems.push(`${at}: ES5+ static ${node.object.name}.${node.property.name}`);
        }
      }
      if (node.type === 'Property' && node.key.type === 'Identifier' && RESERVED_ES3.has(node.key.name)) {
        problems.push(`${at}: reserved word as object key ${node.key.name}`);
      }
      if (node.type === 'Identifier' && ES5_GLOBALS.has(node.name)) problems.push(`${at}: ES5+ global ${node.name}`);
      if (node.type === 'ArrayExpression') {
        if (node.elements.some((e) => e === null)) problems.push(`${at}: array hole`);
        const last = node.elements[node.elements.length - 1];
        if (last && /,/.test(src.slice(last.end, node.end))) problems.push(`${at}: trailing comma in array`);
      }
      if (node.type === 'WithStatement' || node.type === 'DebuggerStatement') problems.push(`${at}: ${node.type}`);
      if ((node.type === 'FunctionDeclaration') && node.body && node.body.type !== 'BlockStatement') problems.push(`${at}: odd function`);
    });
    // functions sent to Illustrator through BridgeTalk (named ...Core) must be plain ASCII
    walk.simple(ast, {
      FunctionDeclaration(node) {
        if (/Core$/.test(node.id.name) && /[^\x00-\x7f]/.test(src.slice(node.start, node.end))) {
          problems.push(`line ${node.loc.start.line}: ${node.id.name}() is sent through BridgeTalk and must be ASCII only`);
        }
      },
    });
    // function declarations inside blocks (if/for/while) are not portable in ES3
    walk.ancestor(ast, {
      FunctionDeclaration(node, ancestors) {
        const parent = ancestors[ancestors.length - 2];
        const grand = ancestors[ancestors.length - 3];
        const ok = parent.type === 'Program' || (parent.type === 'BlockStatement' && grand &&
          (grand.type === 'FunctionDeclaration' || grand.type === 'FunctionExpression'));
        if (!ok) problems.push(`line ${node.loc.start.line}: function declaration inside a block (${node.id.name})`);
      },
    });
  }
  if (problems.length) {
    failures++;
    console.log(`FAIL ${file}`);
    for (const p of problems) console.log('   - ' + p);
  } else {
    console.log(`ok   ${file}`);
  }
}
process.exit(failures ? 1 : 0);
