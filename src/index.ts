import { Hono } from 'hono';
import { cors } from 'hono/cors';
import auth from './routes/auth';
import trades from './routes/trades';

const app = new Hono();

app.use('*', cors());

app.route('/api/auth', auth);
app.route('/api/trades', trades);

// WebSocket endpoint for real‑time price updates (simulated)
app.get('/ws', (c) => {
  const upgrade = c.req.header('Upgrade');
  if (upgrade === 'websocket') {
    return Bun.upgrade(c.req.raw, {
      // You can pass custom data to the WebSocket handler
    });
  }
  return c.text('WebSocket upgrade required', 426);
});

// WebSocket handler (Bun's native)
Bun.serve({
  fetch: app.fetch,
  websocket: {
    open(ws) {
      console.log('WebSocket opened');
      // Start sending simulated price updates
      const interval = setInterval(() => {
        const price = 50000 + Math.random() * 1000;
        ws.send(JSON.stringify({ type: 'price', symbol: 'BTC/USD', price }));
      }, 1000);

      ws.send(JSON.stringify({ type: 'connected' }));
      // Store interval to clear on close
      (ws as any).interval = interval;
    },
    message(ws, message) {
      // Handle incoming messages (e.g., subscribe to specific symbols)
      console.log('Received:', message);
    },
    close(ws) {
      clearInterval((ws as any).interval);
      console.log('WebSocket closed');
    },
  },
  port: 3001,
});

console.log('Backend running on http://localhost:3001');
