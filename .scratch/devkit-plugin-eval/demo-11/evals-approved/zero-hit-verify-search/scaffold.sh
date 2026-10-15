#!/bin/bash
set -e
mkdir -p 'src/auth'
cat > 'src/auth/middleware.ts' <<'PE_EOF_1'
import type { Request, Response, NextFunction } from "express";
import { validateToken } from "./token";
import { loadSession } from "./session";

export async function requireAuth(req: Request, res: Response, next: NextFunction) {
  const header = req.headers.authorization ?? "";
  const token = header.startsWith("Bearer ") ? header.slice(7) : "";
  if (!token) {
    return res.status(401).json({ error: "missing token" });
  }
  const claims = await validateToken(token);
  if (!claims) {
    return res.status(401).json({ error: "invalid token" });
  }
  req.session = await loadSession(claims.sub);
  next();
}

export function requireRole(role: string) {
  return (req: Request, res: Response, next: NextFunction) => {
    if (!req.session?.roles.includes(role)) {
      return res.status(403).json({ error: "forbidden" });
    }
    next();
  };
}
PE_EOF_1
mkdir -p 'src/auth'
cat > 'src/auth/token.ts' <<'PE_EOF_2'
import { createHmac, timingSafeEqual } from "crypto";

const SECRET = process.env.AUTH_SECRET ?? "dev-secret";

export interface Claims {
  sub: string;
  exp: number;
  roles: string[];
}

export async function validateToken(token: string): Promise<Claims | null> {
  const [body, sig] = token.split(".");
  if (!body || !sig) return null;
  const expected = createHmac("sha256", SECRET).update(body).digest("base64url");
  if (expected.length !== sig.length) return null;
  if (!timingSafeEqual(Buffer.from(expected), Buffer.from(sig))) return null;
  const claims = JSON.parse(Buffer.from(body, "base64url").toString()) as Claims;
  if (claims.exp * 1000 < Date.now()) return null;
  return claims;
}

export function signToken(claims: Claims): string {
  const body = Buffer.from(JSON.stringify(claims)).toString("base64url");
  const sig = createHmac("sha256", SECRET).update(body).digest("base64url");
  return `${body}.${sig}`;
}
PE_EOF_2
mkdir -p 'src/auth'
cat > 'src/auth/session.ts' <<'PE_EOF_3'
import { redis } from "../lib/redis";

export interface Session {
  userId: string;
  roles: string[];
  createdAt: number;
}

export async function loadSession(userId: string): Promise<Session> {
  const raw = await redis.get(`session:${userId}`);
  if (raw) return JSON.parse(raw) as Session;
  const fresh: Session = { userId, roles: ["user"], createdAt: Date.now() };
  await redis.set(`session:${userId}`, JSON.stringify(fresh), "EX", 3600);
  return fresh;
}
PE_EOF_3
mkdir -p 'src/api'
cat > 'src/api/routes.ts' <<'PE_EOF_4'
import { Router } from "express";
import { requireAuth, requireRole } from "../auth/middleware";
import { listOrders, getOrder } from "./orders";
import { listUsers } from "./users";

export const router = Router();

router.get("/orders", requireAuth, listOrders);
router.get("/orders/:id", requireAuth, getOrder);
router.get("/admin/users", requireAuth, requireRole("admin"), listUsers);
PE_EOF_4
mkdir -p 'src/api'
cat > 'src/api/orders.ts' <<'PE_EOF_5'
import type { Request, Response } from "express";

export async function listOrders(req: Request, res: Response) {
  res.json({ userId: req.session?.userId, orders: [] });
}

export async function getOrder(req: Request, res: Response) {
  res.json({ id: req.params.id, status: "pending" });
}
PE_EOF_5
mkdir -p 'src/api'
cat > 'src/api/users.ts' <<'PE_EOF_6'
import type { Request, Response } from "express";

export async function listUsers(_req: Request, res: Response) {
  res.json({ users: [] });
}
PE_EOF_6
mkdir -p 'src/lib'
cat > 'src/lib/redis.ts' <<'PE_EOF_7'
import Redis from "ioredis";

export const redis = new Redis(process.env.REDIS_URL ?? "redis://localhost:6379");
PE_EOF_7
mkdir -p 'config'
cat > 'config/default.json' <<'PE_EOF_8'
{
  "auth": {
    "legacy_auth_enabled": false,
    "token_ttl_seconds": 3600
  },
  "redis": {
    "url": "redis://localhost:6379"
  }
}
PE_EOF_8
