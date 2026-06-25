---
name: javascript-coder
description: >
  Expert JavaScript coding skill for writing, debugging, refactoring, and optimizing JS code
  across all environments — browser, Node.js, Deno, and edge runtimes. Trigger this skill
  whenever the user asks to write JavaScript or TypeScript, fix JS/TS bugs, build REST or
  GraphQL APIs, create React/Vue/Svelte components, work with the DOM, handle async code
  (Promises, async/await, observables), set up Node.js projects, write unit/integration tests
  with Jest or Vitest, configure bundlers (Vite, webpack, esbuild), or anything else JS/TS-
  related. Also use when the user uploads a .js, .ts, .jsx, .tsx, .mjs, or .cjs file and asks
  for help, or mentions ESModules, CommonJS, closures, event loops, hydration, or SSR. When in
  doubt, use this skill — it's better to over-trigger than miss a JavaScript task.
---

# JavaScript Coder

A skill for writing clean, modern, production-grade JavaScript and TypeScript.

---

## Core Philosophy

- **Modern JS first**: ES2022+ features (optional chaining, nullish coalescing, logical
  assignment, `at()`, `structuredClone`, top-level `await`) unless a legacy target is specified.
- **TypeScript by default**: Prefer `.ts`/`.tsx` for any project with more than one file.
  Plain JS is fine for quick scripts and browser snippets.
- **Functional where it fits**: Prefer pure functions, immutability, and `map/filter/reduce`
  over mutation and loops — but never at the cost of readability.
- **Async done right**: Always `async/await` over raw Promise chains. Catch errors at the
  boundary, not scattered throughout.
- **No magic**: Avoid clever one-liners that need a comment to decode. Code is for humans.

---

## Workflow

### 1. Understand the Task

Before writing, clarify:
- **Runtime**: Browser? Node.js (version)? Deno? Edge (Cloudflare Workers, Vercel)?
- **Module system**: ESM (`import/export`) or CJS (`require`)? Assume ESM unless told otherwise.
- **TypeScript**: Is this a TS project? Should output include `.d.ts` type declarations?
- **Framework**: React, Vue, Svelte, vanilla? SSR or client-only?
- **Existing code**: If a file is uploaded, read it fully before suggesting changes.

### 2. Choose the Right Pattern

| Use Case                        | Pattern / Tool                                  |
|---------------------------------|-------------------------------------------------|
| Browser script / DOM            | Vanilla JS ESM, no bundler needed               |
| React UI component              | Functional component + hooks                    |
| Node.js CLI                     | `process.argv` / `commander` / `yargs`          |
| REST API                        | Express / Fastify / Hono                        |
| Full-stack web app              | Next.js (React) or SvelteKit                    |
| Real-time (WebSockets)          | `ws` / Socket.IO / native WebSocket API         |
| Data fetching                   | `fetch` (native) + `async/await`                |
| State management                | Zustand / Jotai (React); Pinia (Vue)            |
| Background jobs / queues        | BullMQ (Node) / Durable Objects (edge)          |
| Testing                         | Vitest (fast, ESM-native) or Jest               |
| Type-safe API contracts         | tRPC or Zod                                     |

### 3. Write the Code

#### Style & Formatting
- Use **Prettier** defaults: 2-space indent, single quotes, trailing commas, semicolons on.
- Max line length: 100 chars.
- Import order: built-ins → third-party → local (separated by blank lines).
- Prefer named exports; use default exports only for top-level framework components.

#### TypeScript Standards
Always annotate function signatures. Avoid `any` — use `unknown` and narrow:

```typescript
interface User {
  id: number;
  name: string;
  email: string | null;
}

async function fetchUser(id: number): Promise<User | null> {
  const res = await fetch(`/api/users/${id}`);
  if (!res.ok) return null;
  return res.json() as Promise<User>;
}
```

Use `satisfies` to validate shape without widening type:
```typescript
const config = {
  port: 3000,
  host: 'localhost',
} satisfies Record<string, string | number>;
```

#### Async / Error Handling
Never leave Promises unhandled. Catch errors at the call boundary:

```typescript
// Good — boundary catch
async function loadData(url: string) {
  try {
    const res = await fetch(url);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return await res.json();
  } catch (err) {
    console.error('Failed to load data:', err);
    throw err; // re-throw so callers can react
  }
}
```

For parallel work, use `Promise.all` (fail-fast) or `Promise.allSettled` (handle each):
```typescript
const [users, posts] = await Promise.all([fetchUsers(), fetchPosts()]);
```

#### DOM Manipulation
Prefer `querySelector` + declarative event delegation over imperative loops:

```javascript
document.querySelector('#app').addEventListener('click', (e) => {
  const btn = e.target.closest('[data-action]');
  if (!btn) return;
  handleAction(btn.dataset.action, btn.dataset.id);
});
```

#### React Patterns
Prefer hooks and composition over HOCs:

```tsx
// Custom hook — encapsulate fetch logic
function useUser(id: number) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    fetchUser(id).then((u) => {
      if (!cancelled) { setUser(u); setLoading(false); }
    });
    return () => { cancelled = true; };
  }, [id]);

  return { user, loading };
}

// Component stays clean
function UserCard({ id }: { id: number }) {
  const { user, loading } = useUser(id);
  if (loading) return <Spinner />;
  if (!user) return <p>Not found</p>;
  return <div>{user.name}</div>;
}
```

Rules:
- No mutation of state directly — always use the setter
- Avoid `useEffect` for derived state — use `useMemo`
- Memoize expensive components with `React.memo`; callbacks with `useCallback`
- Use `key` props correctly — never use array index as key for dynamic lists

#### Node.js Specifics
```typescript
// File I/O — always use fs/promises
import { readFile, writeFile } from 'node:fs/promises';

const data = await readFile('input.json', 'utf8');
const parsed = JSON.parse(data);
await writeFile('output.json', JSON.stringify(parsed, null, 2));
```

Always use `node:` prefix for built-in imports (`node:path`, `node:fs`, `node:crypto`).

Environment variables:
```typescript
const PORT = Number(process.env.PORT ?? 3000);
const DB_URL = process.env.DATABASE_URL;
if (!DB_URL) throw new Error('DATABASE_URL is required');
```

#### Closures & Scope Gotchas
```javascript
// BAD — var in loop, all callbacks capture same i
for (var i = 0; i < 3; i++) {
  setTimeout(() => console.log(i), 100); // prints 3, 3, 3
}

// GOOD — let creates block scope per iteration
for (let i = 0; i < 3; i++) {
  setTimeout(() => console.log(i), 100); // prints 0, 1, 2
}
```

---

## Testing

Use **Vitest** (ESM-native, fast, Jest-compatible API):

```typescript
import { describe, it, expect, vi } from 'vitest';
import { parseAmount } from './utils';

describe('parseAmount', () => {
  it('parses a valid dollar string', () => {
    expect(parseAmount('$12.50')).toBe(12.5);
  });

  it('returns null for invalid input', () => {
    expect(parseAmount('abc')).toBeNull();
    expect(parseAmount('')).toBeNull();
  });

  it('handles zero', () => {
    expect(parseAmount('$0.00')).toBe(0);
  });
});

// Mocking
vi.mock('./api', () => ({ fetchUser: vi.fn().mockResolvedValue({ id: 1, name: 'Alex' }) }));
```

Structure:
- **Unit tests**: Pure functions, utilities, hooks (with `@testing-library/react`)
- **Integration tests**: API routes, DB queries (use a test DB or in-memory SQLite)
- **E2E tests**: Playwright for critical user flows

---

## Project Structure

### Node.js / API
```
project/
├── src/
│   ├── index.ts          ← entry point
│   ├── routes/
│   ├── services/
│   ├── models/
│   └── utils/
├── tests/
├── package.json
├── tsconfig.json
└── .env.example
```

### React (Vite)
```
project/
├── src/
│   ├── main.tsx
│   ├── App.tsx
│   ├── components/
│   ├── hooks/
│   ├── pages/
│   ├── store/
│   └── lib/              ← utilities, api clients
├── public/
├── index.html
├── vite.config.ts
└── tsconfig.json
```

### Minimal `package.json`
```json
{
  "name": "my-app",
  "version": "1.0.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc && vite build",
    "test": "vitest",
    "lint": "eslint src --ext .ts,.tsx"
  }
}
```

### Minimal `tsconfig.json`
```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "ESNext",
    "moduleResolution": "bundler",
    "strict": true,
    "noUncheckedIndexedAccess": true,
    "skipLibCheck": true
  }
}
```

---

## Common Patterns & Snippets

### Debounce
```typescript
function debounce<T extends (...args: unknown[]) => void>(fn: T, ms: number): T {
  let timer: ReturnType<typeof setTimeout>;
  return ((...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), ms);
  }) as T;
}
```

### Deep Clone (modern)
```javascript
const clone = structuredClone(original); // no lodash needed
```

### Safe JSON Parse
```typescript
function safeJson<T>(raw: string): T | null {
  try { return JSON.parse(raw) as T; }
  catch { return null; }
}
```

### Fetch with Timeout
```typescript
async function fetchWithTimeout(url: string, ms = 5000) {
  const controller = new AbortController();
  const id = setTimeout(() => controller.abort(), ms);
  try {
    const res = await fetch(url, { signal: controller.signal });
    return res;
  } finally {
    clearTimeout(id);
  }
}
```

### Group Array by Key (ES2024)
```typescript
const byStatus = Object.groupBy(tasks, (t) => t.status);
// no lodash needed
```

### Zod Schema Validation
```typescript
import { z } from 'zod';

const UserSchema = z.object({
  id: z.number(),
  email: z.string().email(),
  role: z.enum(['admin', 'user']),
});

type User = z.infer<typeof UserSchema>;

const user = UserSchema.parse(rawInput); // throws on invalid
const result = UserSchema.safeParse(rawInput); // { success, data/error }
```

---

## Debugging Checklist

1. Check the **console** — read the full error including stack trace
2. `typeof x`, `Array.isArray(x)`, `x instanceof Y` to verify types at runtime
3. `console.log(JSON.stringify(obj, null, 2))` for deep objects
4. Use `debugger;` statement + DevTools or `--inspect` flag in Node
5. For async bugs: are you `await`-ing everything that returns a Promise?
6. For React re-render issues: install React DevTools, check component state/props

Common gotchas:
- **`this` context**: Arrow functions don't bind `this` — use them in callbacks
- **`==` vs `===`**: Always use `===`
- **`undefined` vs `null`**: Optional chaining `?.` guards both; `??` only guards `null`/`undefined`
- **Floating point**: `0.1 + 0.2 !== 0.3` — use integers or a library for money
- **`async` forEach**: `array.forEach(async fn)` does NOT await — use `for...of` or `Promise.all`

```javascript
// BAD — won't await
items.forEach(async (item) => { await save(item); });

// GOOD — sequential
for (const item of items) { await save(item); }

// GOOD — parallel
await Promise.all(items.map((item) => save(item)));
```

---

## Output Format

- Output **complete, runnable code** — no `...` placeholders unless explaining a pattern
- For multi-file output, show each file with its path as a comment at the top:
  ```typescript
  // src/services/user.ts
  ```
- When fixing a bug, briefly explain **what was wrong** and **why the fix works**
- When refactoring, note any **behavior changes** (even intentional ones)
- For React, prefer `.tsx`; for plain Node utilities, prefer `.ts`

---

## Reference Files

For domain-specific guidance, see:

- `references/typescript-advanced.md` — generics, conditional types, template literals, `infer`
- `references/react-patterns.md` — Suspense, Context, compound components, render props
- `references/node-apis.md` — streams, workers, child_process, crypto, http2
- `references/testing-advanced.md` — MSW for API mocking, Playwright E2E, snapshot testing
- `references/bundlers.md` — Vite config, esbuild plugins, webpack migration

_(Load only the reference relevant to the current task.)_
