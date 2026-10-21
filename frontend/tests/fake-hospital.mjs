// A stand-in for the hospital service's private API for the browser tests:
// the record files the platform downloads (docs/history-events.md, section 2).
//
// GET /platform/records/:record/files/:file   (X-Platform-Key required)
//
// Every file id starting with "a" is the PNG below, anything else the PDF.
// tests/seed.py declares the same bytes (size and SHA-256) when it
// publishes records, so the platform's checks pass.
import http from 'node:http';

const PORT = Number(process.env.FAKE_HOSPITAL_PORT ?? 8013);
const KEY = process.env.PLATFORM_ADMIN_KEY ?? 'e2e-platform-key';

// An 8x8 PNG and a one-page PDF.
export const PNG = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAgAAAAICAIAAABLbSncAAAAEUlEQVR4nGMQaEjAihiGlgQAXiE8AWpkQeQAAAAASUVORK5CYII=',
  'base64',
);
export const PDF = Buffer.from(
  '%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n' +
    '3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n',
  'latin1',
);

http
  .createServer((req, res) => {
    const url = new URL(req.url ?? '/', `http://127.0.0.1:${PORT}`);
    if (url.pathname === '/health') {
      res.writeHead(200, { 'Content-Type': 'application/json' });
      return res.end('{"ok":true}');
    }
    if (req.headers['x-platform-key'] !== KEY) {
      res.writeHead(401);
      return res.end();
    }
    const match = url.pathname.match(/^\/platform\/records\/([0-9a-f]{32})\/files\/([0-9a-f]{32})$/);
    if (req.method !== 'GET' || !match) {
      res.writeHead(404);
      return res.end();
    }
    const png = match[2].startsWith('a');
    const body = png ? PNG : PDF;
    res.writeHead(200, { 'Content-Type': png ? 'image/png' : 'application/pdf', 'Content-Length': body.length });
    res.end(body);
  })
  .listen(PORT, '127.0.0.1');
