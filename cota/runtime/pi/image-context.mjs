/** Request-only image evidence selection. Durable messages retain original pixels. */
import {createHash} from 'node:crypto';
import {posix} from 'node:path';

export const IMAGE_RESOURCE_ROOT = '/bot/.cota/context-images/';

/** Per-run capabilities: catalog membership authorizes RPC bytes, never host paths. */
export function createImageResources(initial = [], request) {
  const catalog = new Map(), paths = new Map(), loaded = new Map(), fingerprints = new Map();
  const register = descriptors => {
    for (const value of descriptors ?? []) {
      const {id, path, mimeType, size} = value;
      if (typeof id !== 'string' || !/^(sha256:[a-f0-9]{64}|f_[A-Za-z0-9_-]+)$/.test(id)
          || typeof path !== 'string' || !path.startsWith(IMAGE_RESOURCE_ROOT) || path !== posix.normalize(path)
          || !/^image\/(png|jpeg|webp|gif|bmp)$/.test(mimeType) || !Number.isSafeInteger(size) || size < 0)
        throw new Error('Invalid image resource descriptor');
      const descriptor = {id, path, mimeType, size}, previous = catalog.get(id), owner = paths.get(path);
      if (previous && JSON.stringify(previous) !== JSON.stringify(descriptor) || owner && owner.id !== id)
        throw new Error('Immutable image resource descriptor changed');
      catalog.set(id, descriptor); paths.set(path, descriptor);
    }
  };
  const descriptor = id => {
    const result = catalog.get(id);
    if (!result) throw new Error('Unknown image resource');
    return result;
  };
  register(initial);
  return {register, descriptor, forId: id => catalog.get(id), forPath: path => paths.get(path),
    fingerprint: id => fingerprints.get(id), get size() {return catalog.size;},
    async load(id) {
      const resource = descriptor(id);
      if (!loaded.has(id)) {
        const pending = (async () => {
          const block = await request('image_resource', {id});
          if (block?.error) throw Object.assign(new Error('Image resource unavailable; contents not reviewed'),
            {code: 'image_resource_unavailable'});
          if (block?.type !== 'image' || block.mimeType !== resource.mimeType || typeof block.data !== 'string')
            throw new Error('Image resource MIME/type mismatch');
          const bytes = Buffer.from(block.data, 'base64');
          if (bytes.length !== resource.size || bytes.toString('base64') !== block.data)
            throw new Error('Image resource size/encoding mismatch');
          const hash = `sha256:${createHash('sha256').update(bytes).digest('hex')}`;
          if (id.startsWith('sha256:') && hash !== id)
            throw new Error('Image resource hash mismatch');
          fingerprints.set(id, hash);
          return {...block, cotaImageSource: {attachment_id: id, path: resource.path}};
        })();
        loaded.set(id, pending);
        pending.catch(() => loaded.delete(id));
      }
      const pending = loaded.get(id);
      loaded.delete(id); loaded.set(id, pending);
      while (loaded.size > 8) loaded.delete(loaded.keys().next().value);
      return pending;
    }};
}

function currentImageMessages(messages) {
  const latestUser = messages.findLastIndex(m => m.role === 'user' && !m.cotaCompaction && !m.cotaDeferred);
  const boundary = messages.findLastIndex(m => !m.cotaDeferred && (m.role === 'assistant' || m.role === 'user'));
  return (message, index) => !message.cotaDeferred
    && (index === latestUser || message.role === 'toolResult' && index > boundary);
}

/** Fetch current evidence only, after checking known sizes without loading bytes. */
export async function hydrateImageRefs(messages, resources, settings) {
  const active = currentImageMessages(messages), selected = new Map();
  const sizes = new Map();
  for (const [index, message] of messages.entries()) {
    if (!active(message, index)) continue;
    for (const block of Array.isArray(message.content) ? message.content : []) if (block.type === 'image')
      sizes.set(contentHash(block), Buffer.byteLength(block.data, 'base64'));
    for (const ref of message.cotaImageRefs ?? []) {
      if (ref.auto === false) continue;
      const resource = resources.descriptor(ref.id);
      if (ref.path !== resource.path || ref.mimeType !== resource.mimeType || ref.size !== resource.size
          || !Number.isInteger(ref.index) || message.content?.[ref.index]?.type !== 'text')
        throw new Error('Image reference does not match its registered resource');
      selected.set(ref.id, resource); sizes.set(resources.fingerprint(ref.id) ?? ref.id, resource.size);
    }
  }
  const total = [...sizes.values()].reduce((sum, size) => sum + size, 0);
  if (sizes.size > settings.maxImages || total > settings.maxImageBytes)
    throw new Error('Current user input/tool batch exceeds the image budget; use fewer/smaller images');
  if ([...sizes.values()].reduce((sum, size) => sum + Math.ceil(size / 3) * 4, 0) > settings.maxRequestBytes)
    throw new Error('Current user input/tool batch exceeds the byte budget; use fewer/smaller images');
  const images = new Map();
  for (const id of selected.keys()) {
    try {images.set(id, await resources.load(id));}
    catch (error) {
      if (error.code !== 'image_resource_unavailable') throw error;
      images.set(id, {type: 'text', text: `Image resource ${JSON.stringify(selected.get(id))} unavailable; contents not reviewed. Use read to retry.`});
    }
  }
  return messages.map((message, index) => {
    if (!message.cotaImageRefs?.length) return message;
    if (!active(message, index)) {
      // Pi keeps only the head of long tool text in summaries. Preserve lean
      // source references first; their private indexes still name raw evidence.
      const indexes = new Set(message.cotaImageRefs.map(ref => ref.index));
      return {...message, cotaImagePixelsOmitted: true, content: [
        ...message.cotaImageRefs.map(ref => message.content[ref.index]),
        ...message.content.filter((_block, blockIndex) => !indexes.has(blockIndex))]};
    }
    const content = [...message.content];
    for (const ref of message.cotaImageRefs) if (ref.auto !== false) content[ref.index] = images.get(ref.id);
    return {...message, content, cotaAttachmentsHydrated: true};
  });
}

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

export function projectImageContext(messages, resources) {
  // A batch is current until the next assistant response or user input. Keep
  // all images returned by its tool calls, including side-by-side comparisons.
  const current = currentImageMessages(messages);
  const calls = new Map(), visible = new Map();
  return messages.map((message, index) => {
    if (!Array.isArray(message.content)) return message;
    if (message.role === 'assistant') for (const block of message.content)
      if (block.type === 'toolCall') calls.set(block.id, block);
    if (!message.content.some(block => block.type === 'image')) return message;
    const call = message.role === 'toolResult' ? calls.get(message.toolCallId) : undefined;
    const active = current(message, index);
    const references = [];
    const content = message.content.flatMap((block, imageIndex) => {
      if (block.type !== 'image') return [block];
      const hash = contentHash(block), source = block.cotaImageSource ?? {};
      const id = source.attachment_id ?? message.cotaEventId ?? message.toolCallId ?? `message-${index}`;
      const path = source.path ?? resources?.forId(hash)?.path ?? call?.arguments?.path ?? call?.arguments?.file_path;
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
