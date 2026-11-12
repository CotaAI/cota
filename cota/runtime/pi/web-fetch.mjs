/** Fetch public URLs with smart content processing. Replaces http_request.
 * HTML pages → Readability extraction → Markdown. JSON → pretty-printed. Text → passthrough.
 * SSRF protection validates URLs and DNS results against private/reserved ranges.
 */
import http from 'node:http';
import https from 'node:https';
import {lookup as dnsLookup} from 'node:dns';
import {isIP} from 'node:net';
import {Type} from '@earendil-works/pi-ai';
import {Readability} from '@mozilla/readability';
import {parseHTML} from 'linkedom';
import TurndownService from 'turndown';

const MAX_RAW_BYTES = 1024 * 1024;
const MAX_OUTPUT_LENGTH = 200_000;
const MAX_REDIRECTS = 5;
const METHODS = ['GET', 'POST', 'PUT', 'DELETE', 'PATCH'];
const parameters = Type.Object({
  url: Type.String({description: 'HTTP or HTTPS URL of a public web page or API endpoint'}),
  method: Type.Optional(Type.Union(METHODS.map(method => Type.Literal(method)))),
  headers: Type.Optional(Type.Record(Type.String(), Type.String())),
  body: Type.Optional(Type.String({description: 'JSON string or plain text request body'})),
  timeout_seconds: Type.Optional(Type.Integer({minimum: 1, maximum: 60, description: 'Total timeout in seconds; default 30, maximum 60'})),
}, {additionalProperties: false});

class SafeError extends Error {}

// ---------------------------------------------------------------------------
// SSRF protection
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// Content processing
// ---------------------------------------------------------------------------

const turndown = new TurndownService({headingStyle: 'atx', codeBlockStyle: 'fenced', bulletListMarker: '-'});

function extractContent(html) {
  try {
    const {document} = parseHTML(html);
    const article = new Readability(document).parse();
    if (article && article.content) {
      let md = turndown.turndown(article.content);
      if (article.title) md = `# ${article.title}\n\n${md}`;
      return md;
    }
  } catch {}
  return html
    .replace(/<script[^>]*>[\s\S]*?<\/script>/gi, '')
    .replace(/<style[^>]*>[\s\S]*?<\/style>/gi, '')
    .replace(/<[^>]+>/g, ' ')
    .replace(/[ \t]+/g, ' ')
    .replace(/\n\s*\n/g, '\n\n')
    .trim();
}

function processBody(raw, contentType) {
  const ct = (contentType || '').toLowerCase();
  if (ct.includes('text/html') || ct.includes('application/xhtml')) {
    return extractContent(raw);
  }
  if (ct.includes('application/json') || ct.includes('+json')) {
    try { return JSON.stringify(JSON.parse(raw), null, 2); } catch {}
  }
  return raw;
}

// ---------------------------------------------------------------------------
// HTTP transport
// ---------------------------------------------------------------------------

function fetchOnce(url, method, headers, body, signal, transport, lookup) {
  return new Promise((resolve, reject) => {
    const req = transport(url, {method, headers, signal, agent: false,
      lookup: checkedLookup(lookup)}, response => {
      const chunks = [];
      let bytes = 0;
      response.on('data', chunk => {
        bytes += chunk.length;
        if (bytes > MAX_RAW_BYTES) {
          reject(new SafeError('Response exceeds 1 MiB size limit'));
          response.destroy(); req.destroy();
        } else chunks.push(chunk);
      });
      response.on('error', reject);
      response.on('aborted', () => reject(new SafeError('Response interrupted')));
      response.on('end', () => resolve({
        status: response.statusCode,
        contentType: response.headers['content-type'],
        location: response.headers['location'],
        body: Buffer.concat(chunks).toString('utf8'),
      }));
    });
    req.on('error', reject);
    req.end(body);
  });
}

// ---------------------------------------------------------------------------
// Tool
// ---------------------------------------------------------------------------

/**
 * @param {{request?: typeof http.request, lookup?: typeof dnsLookup}} [dependencies]
 * @returns {import('@earendil-works/pi-agent-core').AgentTool<typeof parameters>}
 */
export function createWebFetchTool({request, lookup = dnsLookup} = {}) {
  return {
    name: 'web_fetch', label: 'Web fetch',
    description: 'Fetch a public URL and return its content. HTML pages are converted to readable Markdown via content extraction; JSON responses are pretty-printed; other text passes through. GET requests follow redirects (up to 5). Responses are size-limited.',
    parameters,
    async execute(toolCallId, args, signal) {
      if (signal?.aborted) throw new DOMException('Web fetch cancelled', 'AbortError');
      let timer, timedOut = false;
      try {
        let url = validateUrl(args.url);
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
        let redirects = 0;
        let currentUrl = url;
        let response;
        while (true) {
          const transport = request ?? (currentUrl.protocol === 'https:' ? https.request : http.request);
          response = await fetchOnce(currentUrl,
            redirects > 0 ? 'GET' : method,
            redirects > 0 ? {} : headers,
            redirects > 0 ? undefined : args.body,
            requestSignal, transport, lookup);
          if (method === 'GET' && [301, 302, 303, 307, 308].includes(response.status) && response.location) {
            if (++redirects > MAX_REDIRECTS) throw new SafeError('Too many redirects');
            try { currentUrl = validateUrl(new URL(response.location, currentUrl).href); }
            catch (error) {
              if (error instanceof SafeError) throw error;
              throw new SafeError('Invalid redirect target');
            }
            continue;
          }
          break;
        }
        const success = response.status >= 200 && response.status < 300;
        let output = success ? processBody(response.body, response.contentType) : response.body;
        if (output.length > MAX_OUTPUT_LENGTH)
          output = output.slice(0, MAX_OUTPUT_LENGTH) + '\n\n[Content truncated]';
        const details = {status_code: response.status, url: currentUrl.href,
          ...(response.contentType ? {content_type: response.contentType} : {})};
        if (success) return {content: [{type: 'text', text: output}], details, isError: false};
        return {content: [{type: 'text', text: JSON.stringify({...details, error: `HTTP ${response.status}`, body: output})}],
          details: {...details, error: `HTTP ${response.status}`}, isError: true};
      } catch (error) {
        if (signal?.aborted) throw new DOMException('Web fetch cancelled', 'AbortError');
        const message = timedOut ? 'Web fetch timed out'
          : error instanceof SafeError ? error.message : 'Web fetch failed';
        return {content: [{type: 'text', text: JSON.stringify({error: message})}],
          details: {error: message}, isError: true};
      } finally { clearTimeout(timer); }
    },
  };
}
