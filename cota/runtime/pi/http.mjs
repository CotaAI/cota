/** A standalone Pi AgentTool. Native Node transports ignore environment proxies. */
import http from 'node:http';
import https from 'node:https';
import {lookup as dnsLookup} from 'node:dns';
import {isIP} from 'node:net';
import {Type} from '@earendil-works/pi-ai';

const MAX_RESPONSE_BYTES = 256 * 1024;
const METHODS = ['GET', 'POST', 'PUT', 'DELETE', 'PATCH'];
const parameters = Type.Object({
  url: Type.String({description: 'HTTP or HTTPS URL of a public external service'}),
  method: Type.Optional(Type.Union(METHODS.map(method => Type.Literal(method)))),
  headers: Type.Optional(Type.Record(Type.String(), Type.String())),
  body: Type.Optional(Type.String({description: 'JSON string or plain text request body'})),
  timeout_seconds: Type.Optional(Type.Integer({minimum: 1, maximum: 60, description: 'Total timeout in seconds; default 30, maximum 60'})),
}, {additionalProperties: false});

class SafeError extends Error {}

function validateAddress(address) {
  const family = isIP(address);
  let blocked = true;
  if (family === 4) {
    const [a, b, c] = address.split('.').map(Number);
    blocked = a === 0 || a === 10 || a === 127 || a >= 224
      || (a === 100 && b >= 64 && b <= 127) || (a === 169 && b === 254)
      || (a === 172 && b >= 16 && b <= 31)
      || (a === 192 && (b === 168 || (b === 0 && (c === 0 || c === 2)) || (b === 88 && c === 99)))
      || (a === 198 && (b === 18 || b === 19 || (b === 51 && c === 100)))
      || (a === 203 && b === 0 && c === 113);
  } else if (family === 6 && !address.includes('%') && !address.includes('.')) {
    const [left, right] = address.toLowerCase().split('::');
    const head = left ? left.split(':') : [];
    const tail = right ? right.split(':') : [];
    const groups = right === undefined ? head : [...head, ...Array(8 - head.length - tail.length).fill('0'), ...tail];
    const [a, b] = groups.map(group => parseInt(group, 16));
    // Only global unicast is routable. Conservatively reject special-purpose
    // 2001::/23, documentation and 6to4 ranges as well as all mapped addresses.
    blocked = a < 0x2000 || a > 0x3fff || (a === 0x2001 && (b < 0x200 || b === 0xdb8))
      || a === 0x2002 || (a === 0x3fff && b < 0x1000);
  }
  if (blocked) throw new SafeError('Blocked URL (private/reserved IP)');
}

function validateUrl(input) {
  let url;
  try { url = new URL(input); } catch { throw new SafeError('Invalid HTTP URL'); }
  if (!['http:', 'https:'].includes(url.protocol) || !url.hostname)
    throw new SafeError('Invalid URL: only HTTP and HTTPS are supported');
  if (url.username || url.password || /^https?:\/\/[^/?#]*@/i.test(input))
    throw new SafeError('URL credentials are not supported');
  const hostname = url.hostname.replace(/^\[|\]$/g, '').replace(/\.$/, '').toLowerCase();
  if (hostname === 'localhost' || hostname.endsWith('.localhost')) throw new SafeError('Blocked URL (localhost)');
  if (isIP(hostname)) validateAddress(hostname);
  return url;
}

function checkedLookup(lookup) {
  return (hostname, options, callback) => {
    // Validate and return the very same address list consumed by net.connect.
    // Resolving before request() then resolving again would permit DNS rebinding.
    lookup(hostname, {all: true, verbatim: true}, (error, addresses) => {
      if (error) return callback(new SafeError('DNS lookup failed'));
      try {
        if (!addresses?.length) throw new SafeError('DNS lookup returned no addresses');
        for (const {address, family} of addresses) {
          validateAddress(address);
          if (isIP(address) !== family) throw new SafeError('DNS lookup returned invalid address family');
        }
        const family = typeof options === 'number' ? options : options.family;
        const eligible = family ? addresses.filter(address => address.family === family) : addresses;
        if (!eligible.length) throw new SafeError('DNS lookup returned no matching addresses');
        if (options.all) callback(null, eligible);
        else callback(null, eligible[0].address, eligible[0].family);
      } catch (error) { callback(error); }
    });
  };
}

/** @returns {import('@earendil-works/pi-agent-core').AgentToolResult} */
function result(details, isError = false) {
  const {body, ...metadata} = details;
  return {content: [{type: 'text', text: JSON.stringify(details)}], details: metadata, isError};
}

/**
 * Transport dependencies are a code-only testing seam, never user configuration.
 * No proxy, private-network allowlist, or redirect option is exposed to the model.
 * @param {{request?: typeof http.request, lookup?: typeof dnsLookup}} [dependencies]
 * @returns {import('@earendil-works/pi-agent-core').AgentTool<typeof parameters>}
 */
export function createHttpTool({request, lookup = dnsLookup} = {}) {
  return {
    name: 'http_request', label: 'HTTP request',
    description: 'Make an HTTP request to a public external URL with optional headers and JSON/text body. Redirects are disabled; responses are limited to 256 KiB.',
    parameters,
    async execute(toolCallId, args, signal) {
      if (signal?.aborted) throw new DOMException('HTTP request cancelled', 'AbortError');
      let timer, timedOut = false;
      try {
        const url = validateUrl(args.url);
        const method = args.method ?? 'GET';
        const timeout = args.timeout_seconds ?? 30;
        if (!METHODS.includes(method)) throw new SafeError('Unsupported HTTP method');
        if (!Number.isInteger(timeout) || timeout <= 0) throw new SafeError('Timeout must be a positive integer');
        const headers = {...args.headers};
        if (args.body && !Object.keys(headers).some(key => key.toLowerCase() === 'content-type')) {
          try { JSON.parse(args.body); headers['Content-Type'] = 'application/json'; } catch {}
        }
        if (args.body !== undefined && !Object.keys(headers).some(key => ['content-length', 'transfer-encoding'].includes(key.toLowerCase())))
          headers['Content-Length'] = String(Buffer.byteLength(args.body));
        const controller = new AbortController();
        const requestSignal = signal ? AbortSignal.any([signal, controller.signal]) : controller.signal;
        timer = setTimeout(() => { timedOut = true; controller.abort(); }, Math.min(timeout, 60) * 1000);
        const details = await new Promise((resolve, reject) => {
          const transport = request ?? (url.protocol === 'https:' ? https.request : http.request);
          const req = transport(url, {method, headers, signal: requestSignal, agent: false,
            lookup: checkedLookup(lookup)}, response => {
            const chunks = [];
            let bytes = 0;
            response.on('data', chunk => {
              bytes += chunk.length;
              if (bytes > MAX_RESPONSE_BYTES) {
                reject(new SafeError('HTTP response exceeds 256 KiB response size limit'));
                response.destroy(); req.destroy();
              } else chunks.push(chunk);
            });
            response.on('error', reject);
            response.on('aborted', () => reject(new SafeError('HTTP response interrupted')));
            response.on('end', () => {
              // Keep protocol hints, not cookies or arbitrary upstream headers.
              const headers = Object.fromEntries(['content-type', 'retry-after']
                .filter(name => typeof response.headers[name] === 'string')
                .map(name => [name, response.headers[name]]));
              resolve({status_code: response.statusCode,
                ...(Object.keys(headers).length ? {headers} : {}),
                body: Buffer.concat(chunks).toString('utf8')});
            });
          });
          req.on('error', reject);
          req.end(args.body);
        });
        const success = details.status_code >= 200 && details.status_code < 300;
        return result(success ? details : {...details, error: `HTTP ${details.status_code}`}, !success);
      } catch (error) {
        if (signal?.aborted) throw new DOMException('HTTP request cancelled', 'AbortError');
        return result({error: timedOut ? 'HTTP request timed out'
          : error instanceof SafeError ? error.message : 'HTTP request failed'}, true);
      } finally { clearTimeout(timer); }
    },
  };
}
