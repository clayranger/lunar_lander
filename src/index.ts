import { Hono } from 'hono';
import { cors } from 'hono/cors';
import auth from './routes/auth';
import trades from './routes/trades';

const app = new Hono();

app.use('*', cors());

app.route('/api/auth', auth);
app.route('/api/trades', trades);

app.get('/ws', (c) => c.text('WebSocket upgrade required', 426));



Bun.serve({
  port: 3001,
  fetch(req, server) {
    const url = new URL(req.url);

    // Handle WebSocket upgrade on /ws
    if (url.pathname === '/ws') {
      const success = server.upgrade(req);
      if (success) {
        return; // important: do NOT return a Response
      }
      return new Response('WebSocket upgrade failed', { status: 400 });
    }

    // Everything else goes through Hono
    return app.fetch(req);
  },
  websocket: {
    open(ws) {
      console.log('WebSocket opened');
      const interval = setInterval(() => {
        const price = 50000 + Math.random() * 1000;
        ws.send(JSON.stringify({ type: 'price', symbol: 'BTC/USD', price }));
      }, 1000);

      ws.send(JSON.stringify({ type: 'connected' }));
      (ws as any).interval = interval;
    },
    message(ws, message) {
      console.log('Received:', message);
    },
    close(ws) {
      clearInterval((ws as any).interval);
      console.log('WebSocket closed');
    },
  },
});

console.log('Backend running on http://localhost:3001');
