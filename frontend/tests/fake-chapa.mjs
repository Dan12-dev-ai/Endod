// A stand-in for Chapa's API for the browser tests (no network, no keys).
//
// POST /v1/transaction/initialize   starts a payment; the checkout URL is this server's /checkout page
// GET  /v1/transaction/verify/:ref  Chapa's record of the payment (404 if unknown)
// GET  /checkout/:ref               the "payment page": marks it paid (or failed with ?fail=1)
//                                   and sends the browser back to the return URL, as Chapa does
import http from 'node:http';

const PORT = Number(process.env.FAKE_CHAPA_PORT ?? 8012);
const KEY = 'Bearer CHASECK_TEST-e2e';
const payments = new Map();

function send(res, status, body) {
  res.writeHead(status, { 'Content-Type': 'application/json' });
  res.end(JSON.stringify(body));
}

http
  .createServer((req, res) => {
    const url = new URL(req.url ?? '/', `http://127.0.0.1:${PORT}`);
    if (url.pathname === '/health') return send(res, 200, { ok: true });

    const checkout = url.pathname.match(/^\/checkout\/([\w-]+)$/);
    if (checkout) {
      const payment = payments.get(checkout[1]);
      if (!payment) return send(res, 404, { message: 'Unknown payment' });
      payment.status = url.searchParams.get('fail') ? 'failed' : 'success';
      res.writeHead(302, { Location: payment.return_url });
      return res.end();
    }

    if (req.headers.authorization !== KEY) return send(res, 401, { message: 'Invalid API key' });

    if (req.method === 'POST' && url.pathname === '/v1/transaction/initialize') {
      let raw = '';
      req.on('data', (chunk) => (raw += chunk));
      req.on('end', () => {
        let body;
        try {
          body = JSON.parse(raw || '{}');
        } catch {
          return send(res, 400, { message: 'Invalid JSON' });
        }
        payments.set(body.tx_ref, { ...body, status: 'pending' });
        send(res, 200, {
          status: 'success',
          message: 'Hosted Link',
          data: { checkout_url: `http://127.0.0.1:${PORT}/checkout/${body.tx_ref}` },
        });
      });
      return;
    }

    const verify = url.pathname.match(/^\/v1\/transaction\/verify\/([\w-]+)$/);
    if (req.method === 'GET' && verify) {
      const payment = payments.get(verify[1]);
      if (!payment) return send(res, 404, { status: 'failed', message: 'Invalid transaction', data: null });
      return send(res, 200, {
        status: 'success',
        data: {
          status: payment.status,
          amount: payment.amount,
          currency: payment.currency,
          tx_ref: payment.tx_ref,
          reference: `AP${payment.tx_ref.slice(-8)}`,
        },
      });
    }
    send(res, 404, { message: 'Not found' });
  })
  .listen(PORT, '127.0.0.1');
