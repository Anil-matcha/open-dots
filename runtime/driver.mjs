import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { createServer } from 'node:http';
import { mkdir, readdir, stat } from 'node:fs/promises';
import path from 'node:path';
import { chromium } from 'playwright';

const execFileAsync = promisify(execFile);
const port = Number(process.env.PORT || 3000);
const token = process.env.COMPUTER_TOKEN || '';
const workspace = path.resolve(process.env.WORKSPACE || '/workspace');
const computerId = process.env.COMPUTER_ID || 'computer-runtime';
const width = Number(process.env.VIEWPORT_WIDTH || 1280);
const height = Number(process.env.VIEWPORT_HEIGHT || 720);
const commandTimeout = Number(process.env.COMPUTER_COMMAND_TIMEOUT || 30000);

let browser;
let context;
let page;
let server;
let queue = Promise.resolve();

function json(response, statusCode, payload) {
  const body = JSON.stringify(payload);
  response.writeHead(statusCode, {
    'content-type': 'application/json; charset=utf-8',
    'content-length': Buffer.byteLength(body),
    'cache-control': 'no-store',
  });
  response.end(body);
}

function errorPayload(error) {
  return { error: error instanceof Error ? error.message : String(error) };
}

function authorized(request) {
  return Boolean(token) && request.headers['x-computer-token'] === token;
}

// Defense in depth: the provider publishes this server on loopback only, but the
// driver itself binds 0.0.0.0. Reject requests whose Host header is not a local
// address so a manual `docker run -p 3000:3000` cannot silently expose the
// token-guarded routes to the LAN.
const allowedHosts = new Set(
  (process.env.COMPUTER_ALLOWED_HOSTS || '127.0.0.1,localhost,::1')
    .split(',')
    .map((value) => value.trim().toLowerCase())
    .filter(Boolean)
);

function requestHost(request) {
  const raw = String(request.headers['host'] || '').trim().toLowerCase();
  if (raw.startsWith('[')) return raw.slice(1, raw.indexOf(']')); // [::1]:port
  const parts = raw.split(':');
  return parts.length === 2 ? parts[0] : raw;
}

async function readBody(request) {
  const chunks = [];
  for await (const chunk of request) chunks.push(chunk);
  if (!chunks.length) return {};
  const raw = Buffer.concat(chunks).toString('utf8');
  if (raw.length > 1024 * 1024) throw new Error('Request body is too large.');
  try {
    return JSON.parse(raw);
  } catch {
    throw new Error('Request body must be valid JSON.');
  }
}

function enqueue(operation) {
  const next = queue.then(operation, operation);
  queue = next.catch(() => {});
  return next;
}

function assertHttpUrl(value) {
  if (typeof value !== 'string' || value.length > 2048) {
    throw new Error('A browser URL is required and must be at most 2048 characters.');
  }
  const parsed = new URL(value);
  if (!['http:', 'https:'].includes(parsed.protocol) || !parsed.hostname) {
    throw new Error('Browser navigation only accepts absolute HTTP(S) URLs.');
  }
  return parsed.toString();
}

function workspacePath(value) {
  const requested = typeof value === 'string' && value.trim() ? value.trim() : '/workspace';
  if (requested.length > 512 || !requested.startsWith('/')) {
    throw new Error('Computer file paths must be absolute and at most 512 characters.');
  }
  const resolved = path.resolve(requested);
  const relative = path.relative(workspace, resolved);
  if (relative.startsWith('..') || path.isAbsolute(relative)) {
    throw new Error('Computer file paths must stay inside /workspace.');
  }
  return resolved;
}

async function listFiles(requestedPath) {
  const target = workspacePath(requestedPath);
  const entries = await readdir(target, { withFileTypes: true });
  return entries.slice(0, 500).map((entry) => ({
    name: entry.name,
    kind: entry.isDirectory() ? 'directory' : entry.isFile() ? 'file' : 'other',
  }));
}

async function executeCommand(command) {
  if (typeof command !== 'string' || !command.trim()) throw new Error('A terminal command is required.');
  if (command.length > 4000) throw new Error('Terminal commands must be at most 4000 characters.');
  try {
    const result = await execFileAsync('/bin/sh', ['-lc', command], {
      cwd: workspace,
      timeout: commandTimeout,
      maxBuffer: 1024 * 1024,
      env: {
        PATH: process.env.PATH || '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin',
        HOME: '/home/pwuser',
        LANG: 'C.UTF-8',
      },
    });
    return { exit_code: 0, stdout: result.stdout, stderr: result.stderr };
  } catch (error) {
    return {
      exit_code: typeof error.code === 'number' ? error.code : 1,
      stdout: error.stdout || '',
      stderr: error.stderr || error.message,
    };
  }
}

async function handle(request, response) {
  if (!allowedHosts.has(requestHost(request))) {
    json(response, 403, { error: 'Host not allowed. Publish the runtime on loopback only.' });
    return;
  }
  if (!authorized(request)) {
    json(response, 401, { error: 'Computer runtime authentication failed.' });
    return;
  }

  try {
    const body = request.method === 'POST' ? await readBody(request) : {};
    if (request.method === 'GET' && request.url === '/health') {
      json(response, 200, {
        status: 'healthy',
        computer_id: computerId,
        url: page?.url() || 'about:blank',
        width,
        height,
      });
      return;
    }

    const result = await enqueue(async () => {
      if (request.method === 'POST' && request.url === '/navigate') {
        const url = assertHttpUrl(body.url);
        await page.goto(url, { waitUntil: 'domcontentloaded', timeout: commandTimeout });
        return { operation: 'browser.navigate', url: page.url(), title: await page.title() };
      }

      if (request.method === 'POST' && request.url === '/screenshot') {
        const data = await page.screenshot({ type: 'jpeg', quality: 72 });
        return {
          operation: 'screenshot',
          format: 'jpeg',
          width,
          height,
          url: page.url(),
          frame_id: `frame-${Date.now()}`,
          data: data.toString('base64'),
        };
      }

      if (request.method === 'POST' && request.url === '/terminal') {
        return { operation: 'terminal.exec', ...(await executeCommand(body.command)) };
      }

      if (request.method === 'POST' && request.url === '/files') {
        return {
          operation: 'files.list',
          path: workspacePath(body.path),
          entries: await listFiles(body.path),
        };
      }

      if (request.method === 'POST' && request.url === '/input') {
        const event = body.event;
        if (!event || typeof event !== 'object') throw new Error('Computer input must be a JSON object.');
        const type = String(event.type || '').toLowerCase();
        if (type === 'click') {
          await page.mouse.click(Number(event.x), Number(event.y), { button: event.button || 'left' });
        } else if (type === 'keypress') {
          await page.keyboard.press(String(event.key || ''));
        } else if (type === 'type') {
          const text = String(event.text || '');
          if (text.length > 2000) throw new Error('Typed input must be at most 2000 characters.');
          await page.keyboard.type(text);
        } else if (type === 'scroll') {
          await page.mouse.wheel(Number(event.deltaX || 0), Number(event.deltaY || 0));
        } else {
          throw new Error('Supported input types are click, keypress, type, and scroll.');
        }
        return { operation: 'input', accepted: true, type };
      }

      if (request.method === 'GET' && request.url === '/state') {
        return { operation: 'state', url: page.url(), title: await page.title() };
      }

      throw new Error('Runtime route not found.');
    });
    json(response, 200, { computer_id: computerId, ...result });
  } catch (error) {
    json(response, 400, errorPayload(error));
  }
}

async function main() {
  if (!token) throw new Error('COMPUTER_TOKEN is required.');
  await mkdir(workspace, { recursive: true });
  await stat(workspace);
  browser = await chromium.launch({ headless: true });
  context = await browser.newContext({ viewport: { width, height } });
  page = await context.newPage();
  await page.goto('about:blank');

  server = createServer((request, response) => handle(request, response));
  server.listen(port, '0.0.0.0', () => {
    console.log(JSON.stringify({ ready: true, computer_id: computerId, port, width, height }));
  });
}

async function shutdown() {
  if (server) await new Promise((resolve) => server.close(resolve));
  if (browser) await browser.close();
  process.exit(0);
}

process.on('SIGTERM', shutdown);
process.on('SIGINT', shutdown);

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
