import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import ts from 'typescript';
const source = fs.readFileSync(new URL('./src/timing.ts', import.meta.url), 'utf8');
const js = ts.transpileModule(source, {compilerOptions: {target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.ESNext}}).outputText;
const {captionParts, soundVolume} = await import(`data:text/javascript;base64,${Buffer.from(js).toString('base64')}`);
test('captions preserve every character, including newlines and protected words', () => {
  const text = 'これは全文字幕です。'.repeat(10) + '\nOpenAI APIとコンピューターを調べる。';
  const parts = captionParts(text);
  assert.equal(parts.join(''), text);
  assert.ok(parts.some(x => x.includes('コンピューター')));
  assert.ok(parts.every(x => x.length <= 41));
});
test('ducking follows global speech timing and restores music through silence', () => {
  const sound = {from: 60, to: 210, volume: .5, duck: true};
  const lines = [{from: 90, to: 120}];
  const mix = {duck_volume: .2, duck_seconds: .2};
  assert.equal(soundVolume(sound, 0, 30, lines, mix), .5);
  assert.ok(Math.abs(soundVolume(sound, 40, 30, lines, mix) - .1) < 1e-6);
  assert.equal(soundVolume(sound, 80, 30, lines, mix), .5);
  assert.equal(soundVolume({...sound, fade_in: 1}, 0, 30, lines, mix), 0);
});
