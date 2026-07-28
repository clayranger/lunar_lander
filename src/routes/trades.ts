import { Hono } from 'hono';
import { zValidator } from '@hono/zod-validator';
import { z } from 'zod';
import { db } from '../db';
import { verifyToken } from '../auth';

const trades = new Hono();

// Middleware to extract and verify user
trades.use('*', async (c, next) => {
  const authHeader = c.req.header('Authorization');
  if (!authHeader) return c.json({ error: 'Unauthorized' }, 401);
  const token = authHeader.split(' ')[1];
  const payload = verifyToken(token);
  if (!payload) return c.json({ error: 'Invalid token' }, 401);
  c.set('userId', payload.userId);
  await next();
});

const tradeSchema = z.object({
  symbol: z.string(),
  side: z.enum(['buy', 'sell']),
  price: z.number().positive(),
  quantity: z.number().positive(),
});

trades.post('/', zValidator('json', tradeSchema), async (c) => {
  const userId = c.get('userId');
  const { symbol, side, price, quantity } = c.req.valid('json');
  const total = price * quantity;

  const result = db.run(
    'INSERT INTO trades (user_id, symbol, side, price, quantity, total) VALUES (?, ?, ?, ?, ?, ?)',
    [userId, symbol, side, price, quantity, total]
  );

  return c.json({ id: result.lastInsertRowid, userId, symbol, side, price, quantity, total });
});

trades.get('/', async (c) => {
  const userId = c.get('userId');
  const rows = db.query('SELECT * FROM trades WHERE user_id = ? ORDER BY created_at DESC').all(userId);
  return c.json(rows);
});

export default trades;
