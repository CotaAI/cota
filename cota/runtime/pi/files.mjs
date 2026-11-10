/** Conversation delivery primitive, defined with Pi's own AgentTool schema. */
import {Type} from '@earendil-works/pi-ai';

export function createSendFilesTool(execute) {
  return {
    name: 'send_files', label: 'Send files',
    description: 'Commit a reply with one to eight existing workspace files to the current conversation. Files are copied, not exposed as arbitrary paths. Optional text is the attachment caption. This queues delivery; do not claim confirmed receipt or repeat the caption afterwards.',
    parameters: Type.Object({
      paths: Type.Array(Type.String({minLength: 1}), {minItems: 1, maxItems: 8}),
      text: Type.Optional(Type.String({maxLength: 32768})),
    }, {additionalProperties: false}),
    execute,
  };
}
