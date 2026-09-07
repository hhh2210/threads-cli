import { spawn } from 'node:child_process';
import { homedir } from 'node:os';
import { join } from 'node:path';

const commands = new Set(['status', 'doctor', 'search', 'read', 'user', 'scan']);
const eventMethods = ['Network.requestWillBeSent', 'Network.responseReceived', 'Network.loadingFinished'];

// Keep this function self-contained: the same whitelist runs in the browser's
// read-only DOM scope and on observed pagination responses in Node.
export function sanitizeData(data, kind) {
  function post(p) {
    if (!p?.code || !p.user?.username) return null;
    const info = p.text_post_app_info || {};
    return {
      code: p.code, pk: p.pk || p.id,
      user: { username: p.user.username, full_name: p.user.full_name },
      caption: { text: p.caption?.text ?? (info.text_fragments?.fragments || []).map(f => f.plaintext || '').join('') }, taken_at: p.taken_at,
      like_count: p.like_count, detected_language: p.detected_language,
      accessibility_caption: p.accessibility_caption,
      carousel_media: (p.carousel_media || []).map(m => ({ accessibility_caption: m.accessibility_caption })),
      text_post_app_info: {
        is_reply: info.is_reply, is_post_unavailable: info.is_post_unavailable,
        direct_reply_count: info.direct_reply_count, repost_count: info.repost_count,
        has_viewer_replied: info.has_viewer_replied,
        share_info: { quoted_post: { code: info.share_info?.quoted_post?.code } },
      },
    };
  }
  function connection(c, search) {
    if (!Array.isArray(c?.edges) || !c.page_info) return null;
    return {
      edges: c.edges.map(e => {
        const t = search ? e.node?.thread : e.node;
        const items = (t?.thread_items || []).map(i => ({ post: post(i.post) })).filter(i => i.post);
        return search ? { node: { thread: { thread_items: items } } } : { node: { thread_items: items } };
      }),
      page_info: { has_next_page: c.page_info.has_next_page, end_cursor: c.page_info.end_cursor },
    };
  }
  if (kind === 'search') {
    const c = connection(data?.searchResults, true);
    return c ? { searchResults: c } : null;
  }
  if (kind === 'profile') {
    const u = data?.user;
    return u?.username ? { user: {
      username: u.username, full_name: u.full_name, biography: u.biography,
      is_verified: u.is_verified, follower_count: u.follower_count,
    } } : null;
  }
  if (kind === 'post') {
    const result = {};
    if (data?.media) { const p = post(data.media); if (p) result.media = p; }
    const c = connection(data?.data, false) || connection(data, false);
    if (c) result.data = c;
    return Object.keys(result).length ? result : null;
  }
  return {};
}

export const extractPageScript = String.raw`({kind}) => {
  const sanitize = (${sanitizeData.toString()});
  const roots = [];
  let authenticated = false;
  let upstreamError = false;
  function walk(x) {
    if (!x || typeof x !== 'object') return;
    if (x.result?.data) {
      const user = x.result.data.viewer?.user;
      if (user?.pk || user?.id) authenticated = true;
      const safe = sanitize(x.result.data, kind);
      if (safe && Object.keys(safe).length && x.result.errors?.length) upstreamError = true;
      if (safe) roots.push(safe);
    }
    for (const value of Object.values(x)) walk(value);
  }
  for (const script of document.querySelectorAll('script[type="application/json"]')) {
    try { walk(JSON.parse(script.textContent)); } catch {}
  }
  let viewer = null;
  for (const svg of document.querySelectorAll('svg[aria-label]')) {
    if (['Profile','个人主页','個人檔案','個人主頁'].includes(svg.getAttribute('aria-label'))) {
      const href = svg.closest('a')?.getAttribute('href');
      if (href && /^\/@[A-Za-z0-9_.]+\/?$/.test(href)) { viewer = href.slice(2).replace(/\/$/,''); authenticated = true; }
    }
  }
  const loginVisible = !authenticated && /Log in or sign up for Threads|Continue with Instagram|Log in to Threads/.test(document.body.innerText);
  const hasReplies = roots.some(r => r.data?.edges);
  const root = roots.find(r => r.media)?.media;
  const ready = kind === 'status' ? authenticated : roots.length > 0 && (kind !== 'post' || hasReplies || root?.text_post_app_info?.direct_reply_count === 0);
  return {data_roots: roots, authenticated, viewer, login_visible: loginVisible, ready, upstream_error: upstreamError};
}`;

class BrowserFailure extends Error {
  constructor(code, message) { super(message); this.code = code; }
}

class BrowserCollector {
  constructor(tab) { this.tab = tab; this.cursor = 0; this.requests = new Map(); this.pages = []; this.viewer = null; }
  async init() {
    this.cdp = await this.tab.capabilities.get('cdp');
    await this.cdp.send('Network.enable', {});
  }
  async page(req) {
    const target = new URL(req.url);
    const paths = { search: /^\/search$/, status: /^\/$/, profile: /^\/@[A-Za-z0-9_.]+\/?$/, post: /^\/(?:@[A-Za-z0-9_.]+\/post|t)\/[A-Za-z0-9_-]+\/?$/ };
    if (target.protocol !== 'https:' || target.hostname !== 'www.threads.com' || target.port || target.username || target.password || !paths[req.kind]?.test(target.pathname)) {
      throw new BrowserFailure('browser_error', 'Only canonical Threads pages can be collected.');
    }
    this.requests.clear(); this.pages = [];
    this.cursor = (await this.cdp.readEvents({ methods: eventMethods })).cursor;
    if (await this.tab.url() === req.url) await this.tab.reload();
    else await this.tab.goto(req.url);
    const deadline = Date.now() + 25000;
    let page;
    do {
      if (!['www.threads.com', 'threads.com'].includes(new URL(await this.tab.url()).hostname)) {
        throw new BrowserFailure('auth_required', 'Threads redirected to login; complete it in Dia.');
      }
      page = await this.tab.playwright.evaluate(extractPageScript, { kind: req.kind });
      if (page.login_visible) throw new BrowserFailure('auth_required', 'Complete Threads login in Dia.');
      if (page.upstream_error) throw new BrowserFailure('browser_error', 'Threads returned an error in the requested page data.');
      if (page.authenticated && page.ready) {
        this.viewer = page.viewer;
        return page;
      }
      await new Promise(resolve => setTimeout(resolve, 350));
    } while (Date.now() < deadline);
    if (!page?.authenticated) throw new BrowserFailure('auth_required', 'Threads did not confirm the logged-in page.');
    if (page.data_roots.length) return page; // Python marks missing reply data as partial.
    throw new BrowserFailure('schema_changed', 'No recognized Threads data appeared on the page.');
  }
  async drain(wait = 0) {
    let batch;
    do {
      batch = await this.cdp.readEvents({ afterSequence: this.cursor, methods: eventMethods, limit: 1000, timeoutMs: wait });
      this.cursor = batch.cursor;
      if (batch.truncated) throw new BrowserFailure('pagination_unavailable', 'Browser events were truncated; saved pages remain available.');
      for (const event of batch.events) {
        const p = event.params || {};
        if (event.method === 'Network.requestWillBeSent') {
          const request = p.request || {};
          if (!String(request.url).startsWith('https://www.threads.com/')) continue;
          const form = new URLSearchParams(request.postData || '');
          if (form.get('fb_api_req_friendly_name') !== 'BarcelonaSearchResultsRefetchableQuery') continue;
          try { const v = JSON.parse(form.get('variables')); this.requests.set(p.requestId, { after: v.after, query: v.query }); } catch {}
        } else if (event.method === 'Network.responseReceived' && this.requests.has(p.requestId)) {
          const status = p.response?.status;
          if (status === 429) throw new BrowserFailure('rate_limited', 'Threads requested a cooldown.');
          if ([401, 403].includes(status)) throw new BrowserFailure('auth_required', 'Threads requires session verification.');
        } else if (event.method === 'Network.loadingFinished' && this.requests.has(p.requestId)) {
          const request = this.requests.get(p.requestId);
          this.requests.delete(p.requestId);
          const response = await this.cdp.send('Network.getResponseBody', { requestId: p.requestId });
          const body = response.base64Encoded ? Buffer.from(response.body, 'base64').toString('utf8') : response.body;
          const roots = [];
          for (const line of body.replace(/^\s*for\s*\(;;\);/, '').split('\n').filter(x => x.trim())) {
            const data = JSON.parse(line);
            if (data.errors?.length) throw new BrowserFailure('browser_error', 'The browser search query returned an upstream error.');
            const safe = sanitizeData(data.data, 'search');
            if (safe) roots.push(safe);
          }
          if (roots.length) this.pages.push({ ...request, page: { data_roots: roots, authenticated: true, viewer: this.viewer } });
        }
      }
    } while (batch.hasMore);
  }
  async next(req) {
    const current = new URL(await this.tab.url());
    if (current.pathname !== '/search' || current.searchParams.get('q') !== req.query) {
      throw new BrowserFailure('pagination_unavailable', 'The active search changed; collection stopped.');
    }
    await this.drain();
    const take = () => {
      const i = this.pages.findIndex(p => p.after === req.cursor && p.query === req.query);
      return i < 0 ? null : this.pages.splice(i, 1)[0].page;
    };
    const pending = take();
    if (pending) return pending;
    await this.tab.playwright.getByRole('region', { name: 'Column body' }).getByRole('link').last().press('End');
    const deadline = Date.now() + 20000;
    do {
      await this.drain(500);
      const page = take();
      if (page) return page;
    } while (Date.now() < deadline);
    throw new BrowserFailure('pagination_unavailable', 'No matching next page arrived; saved results are partial.');
  }
  async request(req) {
    if (req.action === 'page') return this.page(req);
    if (req.action === 'next_search') return this.next(req);
    throw new BrowserFailure('browser_error', 'Unknown browser collection action.');
  }
}

/** Existing authorized browser only; no cookies, tokens, keychain, or external HTTP replay. */
export async function runBrowserCli(tab, args, options = {}) {
  if (!Array.isArray(args) || !commands.has(args[0]) || args.some(a => typeof a !== 'string')) {
    throw new Error('Expected an allowlisted read command and string arguments.');
  }
  const url = new URL(await tab.url());
  if (url.protocol !== 'https:' || !['www.threads.com', 'threads.com'].includes(url.hostname)) {
    throw new Error('Select a Threads tab in the existing Dia connection.');
  }
  const collector = new BrowserCollector(tab);
  await collector.init();
  const prefix = ['--auth', 'browser'];
  if (options.dataDir) prefix.push('--data-dir', options.dataDir);
  if (options.viewer) prefix.push('--viewer', options.viewer);
  const cliArgs = [...prefix, ...args];
  if (!cliArgs.includes('--json')) cliArgs.push('--json');
  const executable = options.executable ?? join(homedir(), '.local', 'bin', 'threads');
  return await new Promise((resolve, reject) => {
    const child = spawn(executable, cliArgs, { shell: false, stdio: ['pipe', 'pipe', 'ignore'],
      env: { ...process.env, THREADS_BROWSER_BRIDGE: '1' } });
    let buffer = ''; let finalText = ''; let queue = Promise.resolve(); let bytes = 0; let closed = false;
    const timeout = setTimeout(() => child.kill('SIGTERM'), options.timeoutMs ?? 240000);
    child.stdout.setEncoding('utf8');
    child.on('error', () => { clearTimeout(timeout); reject(new Error('Could not start the installed Threads CLI.')); });
    child.stdin.on('error', () => {});
    child.stdout.on('data', chunk => {
      bytes += Buffer.byteLength(chunk);
      if (bytes > 20_000_000) { child.kill('SIGTERM'); return; }
      buffer += chunk;
      let index;
      while ((index = buffer.indexOf('\n')) >= 0) {
        const line = buffer.slice(0, index); buffer = buffer.slice(index + 1);
        let request;
        try { request = JSON.parse(line).bridge_request; } catch {}
        if (!request) { finalText += line + '\n'; continue; }
        queue = queue.then(async () => {
          if (closed) return;
          let reply;
          try { reply = { id: request.id, page: await collector.request(request) }; }
          catch (error) { reply = { id: request.id, error: { code: error instanceof BrowserFailure ? error.code : 'browser_error', message: error instanceof BrowserFailure ? error.message : 'Browser collection failed; inspect the page before retrying.' } }; }
          if (!closed) child.stdin.write(JSON.stringify(reply) + '\n');
        });
      }
    });
    child.on('close', (code, signal) => {
      closed = true; clearTimeout(timeout);
      if (signal) return resolve({ exit_code: 5, ok: false, error: { code: 'interrupted', message: 'Collection stopped; saved pages remain in the evidence store.' } });
      try { resolve({ exit_code: code, ...JSON.parse(finalText + buffer) }); }
      catch { resolve({ exit_code: code || 5, ok: false, error: { code: 'invalid_cli_output', message: 'The CLI did not return structured output.' } }); }
    });
  });
}
