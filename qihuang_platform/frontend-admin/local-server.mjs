// 本地一体化服务：静态托管 + 反向代理到真实 8602
// 浏览器只跟 127.0.0.1:8659 通信，API 由本服务转发，彻底绕开本机对 8602 公网的链路拦截。
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PORT = 8659;
const HOST = '127.0.0.1';
const UPSTREAM = 'http://111.231.63.73:8602';

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.js': 'application/javascript; charset=utf-8',
  '.mjs': 'application/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.ico': 'image/x-icon',
  '.woff': 'font/woff',
  '.woff2': 'font/woff2',
};

// 需要转发的 API 前缀
const PROXY_PREFIXES = ['/admin', '/api', '/dev', '/health', '/kg', '/reasoning', '/annotation'];

function shouldProxy(p) {
  return PROXY_PREFIXES.some((pre) => p === pre || p.startsWith(pre + '/'));
}

function readBody(req) {
  return new Promise((resolve) => {
    const chunks = [];
    req.on('data', (c) => chunks.push(c));
    req.on('end', () => resolve(Buffer.concat(chunks)));
  });
}

async function proxy(req, res, urlPath) {
  const target = UPSTREAM + urlPath + (req.url.includes('?') ? '?' + req.url.split('?')[1] : '');
  const body = ['POST', 'PUT', 'PATCH', 'DELETE'].includes(req.method) ? await readBody(req) : undefined;
  // 过滤掉 hop-by-hop 与 host 头，避免上游拒绝
  const fwd = {};
  for (const [k, v] of Object.entries(req.headers)) {
    const lk = k.toLowerCase();
    if (['host', 'connection', 'content-length'].includes(lk)) continue;
    fwd[k] = v;
  }
  try {
    const upstreamRes = await fetch(target, {
      method: req.method,
      headers: fwd,
      body: body && body.length ? body : undefined,
    });
    const buf = Buffer.from(await upstreamRes.arrayBuffer());
    res.statusCode = upstreamRes.status;
    const passHeaders = ['content-type', 'content-length', 'cache-control', 'access-control-allow-origin', 'access-control-allow-headers', 'access-control-allow-methods'];
    for (const h of passHeaders) {
      const val = upstreamRes.headers.get(h);
      if (val) res.setHeader(h, val);
    }
    res.end(buf);
  } catch (e) {
    res.statusCode = 502;
    res.setHeader('content-type', 'application/json; charset=utf-8');
    res.end(JSON.stringify({ error: 'upstream_unreachable', detail: String(e.message || e) }));
  }
}

function serveStatic(req, res, urlPath) {
  let rel = decodeURIComponent(urlPath);
  if (rel === '/' || rel === '') rel = '/console.html';
  // 防目录穿越
  const filePath = path.normalize(path.join(__dirname, rel));
  if (!filePath.startsWith(__dirname)) {
    res.statusCode = 403;
    res.end('Forbidden');
    return;
  }
  fs.stat(filePath, (err, st) => {
    if (err || !st.isFile()) {
      res.statusCode = 404;
      res.setHeader('content-type', 'text/plain; charset=utf-8');
      res.end('404 Not Found: ' + rel);
      return;
    }
    const ext = path.extname(filePath).toLowerCase();
    res.setHeader('content-type', MIME[ext] || 'application/octet-stream');
    fs.createReadStream(filePath).pipe(res);
  });
}

const server = http.createServer((req, res) => {
  const urlPath = req.url.split('?')[0];
  if (shouldProxy(urlPath)) {
    proxy(req, res, urlPath);
  } else {
    serveStatic(req, res, urlPath);
  }
});

server.listen(PORT, HOST, () => {
  console.log(`[local-server] http://${HOST}:${PORT}  (static + proxy -> ${UPSTREAM})`);
});
