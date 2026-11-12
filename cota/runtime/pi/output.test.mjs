import test from 'node:test';
import assert from 'node:assert/strict';
import {PublicTextGuard, hasToolProtocol} from './output.mjs';

test('streaming keeps partial markers private across every split boundary', () => {
  for (const marker of ['<｜｜DSML｜｜ calls>', '<||DSML|| invoke>', '<DSML invoke>']) {
    for (let split = 1; split < marker.length; split++) {
      const guard = new PublicTextGuard();
      const text = guard.push('Saved.\n' + marker.slice(0,split)) + guard.push(marker.slice(split)) + guard.finish();
      assert.equal(text, 'Saved.\n');
      assert(guard.rejected);
    }
  }
});

test('ordinary prose, XML, and quoted code examples remain unchanged', () => {
  for (const text of ['Hello <world> 1 < 2.', 'DSML is a provider format.',
    'Example: `<｜｜DSML｜｜ calls>` is not a real call.',
    '```xml\n<｜｜DSML｜｜ calls>\n</｜｜DSML｜｜ calls>\n```\nExplanation.',
    '~~~xml\n<｜｜DSML｜｜ calls>\n</｜｜DSML｜｜ calls>\n~~~\nExplanation.',
    'Use <svg> and </svg>.']) {
    const guard = new PublicTextGuard();
    const rendered = [...text].map(c => guard.push(c)).join('') + guard.finish();
    assert.equal(rendered,text);
    assert(!guard.rejected);
    assert(!hasToolProtocol({content:[{type:'text',text}]}));
  }
});

test('escaped or unmatched inline backticks cannot exempt later protocol text', () => {
  for (const text of ['A literal \\` character.\n<｜｜DSML｜｜ calls>',
    'Unclosed `word\n<｜｜DSML｜｜ calls>']) {
    const guard = new PublicTextGuard();
    const preview = [...text].map(c=>guard.push(c)).join('') + guard.finish();
    assert(guard.rejected);
    assert(!preview.includes('DSML') && !preview.includes('<｜'));
    assert(hasToolProtocol({content:[{type:'text',text}]}));
  }
});

test('unterminated reserved markers and multiple content blocks are rejected', () => {
  assert(hasToolProtocol({content:[{type:'text',text:'<｜｜DSM'}]}));
  assert(hasToolProtocol({content:[{type:'text',text:'Saved.'},{type:'text',text:'<DSML invoke>'}]}));
});
