/** Conversation delivery primitive, defined with Pi's own AgentTool schema. */
import {Type} from '@earendil-works/pi-ai';

export function createSendFilesTool(execute, limits = {}) {
  if (!limits || typeof limits !== 'object' || Array.isArray(limits))
    throw new Error('File limits must be an object');
  const maxFileBytes = limits.max_file_bytes ?? 20 * 1024 * 1024;
  const maxAttachments = limits.max_attachments ?? 8;
  if (![maxFileBytes, maxAttachments].every(value => Number.isSafeInteger(value) && value > 0))
    throw new Error('File limits must be positive safe integers');
  return {
    name: 'send_files', label: 'Send files',
    description: `Commit a reply with one to ${maxAttachments} existing workspace files to the current conversation. Maximum per file: ${maxFileBytes} bytes. Check/export artifacts within this limit before sending; an oversized artifact must be reduced and revalidated first. Files are copied, not exposed as arbitrary paths. Optional text is the attachment caption. This queues delivery; do not claim confirmed receipt or repeat the caption afterwards.`,
    parameters: Type.Object({
      paths: Type.Array(Type.String({minLength: 1}), {minItems: 1, maxItems: maxAttachments}),
      text: Type.Optional(Type.String({maxLength: 32768})),
    }, {additionalProperties: false}),
    execute,
  };
}
