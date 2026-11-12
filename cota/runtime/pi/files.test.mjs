import test from 'node:test';
import assert from 'node:assert/strict';
import {createSendFilesTool} from './files.mjs';

test('send_files advertises supplied backend limits in its declaration', async () => {
  const calls = [];
  const tool = createSendFilesTool(async (id, args) => {calls.push({id, args}); return {content: []};},
    {max_file_bytes: 20971520, max_attachments: 4});
  assert.equal(tool.name, 'send_files');
  assert.match(tool.description, /20971520/);
  assert.match(tool.description, /4/);
  assert.equal(tool.parameters.properties.paths.maxItems, 4);
  assert.equal(tool.parameters.properties.paths.minItems, 1);
  assert.equal(tool.parameters.additionalProperties, false);
  const args = {paths: ['book.pdf'], text: 'Review copy'};
  await tool.execute('send', args);
  assert.deepEqual(calls, [{id: 'send', args}]);
});

test('send_files default declaration remains a bounded eight-file primitive', () => {
  const tool = createSendFilesTool(async () => ({}));
  assert.match(tool.description, /20971520/);
  assert.equal(tool.parameters.properties.paths.maxItems, 8);
});

for (const limits of [{max_file_bytes: 0}, {max_file_bytes: -1}, {max_file_bytes: 1.2},
  {max_attachments: 0}, {max_attachments: -1}, {max_attachments: 2.5}])
  test(`invalid supplied file limits fail before a callable tool is exposed: ${JSON.stringify(limits)}`, () => {
    assert.throws(() => createSendFilesTool(async () => ({}), limits), /limit/i);
  });

for (const limits of [null, [], 'invalid', {max_file_bytes: '20'}, {max_attachments: Infinity}])
  test(`malformed backend file limits are rejected: ${JSON.stringify(limits)}`, () => {
    assert.throws(() => createSendFilesTool(async () => ({}), limits), /limit/i);
  });
