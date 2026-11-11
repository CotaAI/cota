/** Request-only image evidence selection. Durable messages retain original pixels. */
import {createHash} from 'node:crypto';

// Image blocks are immutable evidence. Avoid hashing the same Base64 payload on
// every model turn without retaining images after their raw messages disappear.
const hashes = new WeakMap();
function contentHash(block) {
  let hash = hashes.get(block);
  if (!hash) {
    hash = `sha256:${createHash('sha256').update(Buffer.from(block.data ?? '', 'base64')).digest('hex')}`;
    hashes.set(block, hash);
  }
  return hash;
}

export function projectImageContext(messages) {
  const latestUser = messages.findLastIndex(m => m.role === 'user' && !m.cotaCompaction);
  // A batch is current until the next assistant response or user input. Keep
  // all images returned by its tool calls, including side-by-side comparisons.
  const boundary = messages.findLastIndex(m => m.role === 'assistant' || m.role === 'user');
  const calls = new Map(), visible = new Map();
  return messages.map((message, index) => {
    if (!Array.isArray(message.content)) return message;
    if (message.role === 'assistant') for (const block of message.content)
      if (block.type === 'toolCall') calls.set(block.id, block);
    if (!message.content.some(block => block.type === 'image')) return message;
    const call = message.role === 'toolResult' ? calls.get(message.toolCallId) : undefined;
    const active = index === latestUser || message.role === 'toolResult' && index > boundary;
    const references = [];
    const content = message.content.flatMap((block, imageIndex) => {
      if (block.type !== 'image') return [block];
      const hash = contentHash(block), source = block.cotaImageSource ?? {};
      const id = source.attachment_id ?? message.cotaEventId ?? message.toolCallId ?? `message-${index}`;
      const path = source.path ?? call?.arguments?.path ?? call?.arguments?.file_path;
      const label = JSON.stringify({source_id: id, ...(path ? {path} : {}), image_index: imageIndex, hash});
      const duplicate = active && visible.get(hash);
      if (active && !duplicate) {
        visible.set(hash, id);
        references.push({type: 'text', text: `Image source ${label}. Not review/approval.`});
        return [block];
      }
      references.push({type: 'text', text: `Image pixels omitted ${label}${duplicate ? `; duplicate of ${duplicate}` : ''}. `
        + 'Not review/approval; re-read source to inspect (files may change).'});
      return [];
    });
    // Pi truncates tool-result text during summarization. Put short provenance
    // before potentially long original text without modifying that evidence.
    return {...message, content: [...references, ...content], ...(content.filter(b => b.type === 'image').length
      < message.content.filter(b => b.type === 'image').length ? {cotaImagePixelsOmitted: true} : {})};
  });
}
