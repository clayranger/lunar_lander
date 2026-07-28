import { Hono } from 'hono';
import { z } from 'zod';
import { zValidator } from '@hono/zod-validator';
import { db } from '../db';
import { hashPassword, comparePassword, generateToken } from '../auth';

const auth = new Hono();

const registerSchema = z.object({
  email: z.string().email(),
  password: z.string().min(6),
});

auth.post('/register', zValidator('json', registerSchema), async (c) => {
  const { email, password } = c.req.valid('json');
  const hashed = hashPassword(password);

  try {
    const result = db.run('INSERT INTO users (email, password) VALUES (?, ?)', [email, hashed]);
    const token = generateToken(result.lastInsertRowid as number);
    return c.json({ token, user: { id: result.lastInsertRowid, email } });
  } catch (err) {
    return c.json({ error: 'Email already exists' }, 400);
  }
});

const loginSchema = z.object({
  email: z.string().email(),
  password: z.string(),
});

auth.post('/login', zValidator('json', loginSchema), async (c) => {
  const { email, password } = c.req.valid('json');
  const user = db.query('SELECT * FROM users WHERE email = ?').get(email) as any;
  if (!user || !comparePassword(password, user.password)) {
    return c.json({ error: 'Invalid credentials' }, 401);
  }
  const token = generateToken(user.id);
  return c.json({ token, user: { id: user.id, email: user.email } });
});

export default auth;
