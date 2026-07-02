---
name: frontend-design-v2
description: >
  Create distinctive, production-grade frontend interfaces with intentional visual engineering
  and zero "AI slop" aesthetics. Use this skill for ANY frontend task: web components, landing
  pages, dashboards, React/Vue/Svelte apps, HTML/CSS layouts, UI systems, posters, or interactive
  experiences. Trigger whenever the user says "build", "design", "make", "create", "style", or
  "beautify" anything visual — even if they don't use the word "design". Also trigger when the
  user wants to improve how something looks, wants a specific aesthetic (dark, glassmorphic,
  minimal, editorial, brutalist, etc.), or asks for a UI with real polish. If there's any visual
  output involved, this skill should be active.
---

# Frontend Design: Visual Engineering & Aesthetic Intentionality

This skill guides creation of high-fidelity, production-grade frontend interfaces.
The goal is **intentionality at every layer** — typography, color, motion, composition,
and code — to eliminate "AI slop": the predictable, averaged aesthetics that make generated
UIs indistinguishable from each other.

---

## Step 0: Concept Kick-off (Do This Before Any Code)

Ask: **What is the one thing someone will remember about this interface?**

Commit to a bold direction from the menu below — or invent one that fits better.
Half-measures produce mediocre results. Push each direction to its logical extreme.

| Direction | Defining Moves |
|---|---|
| **Neo-Brutalist** | Hard shadows (`8px 8px 0 #000`), raw borders (`border-4`), monospace fonts, high contrast, zero softness |
| **Swiss International** | Strict grid, massive tight-tracked sans-serif, generous whitespace (64px+), sparse ornamentation |
| **Organic / Glassmorphic** | 32px+ radii, layered backdrop blurs, muted earthy palette, spring-physics motion |
| **Editorial / Magazine** | Serif display type, asymmetric bleeds, off-black ink colors, pull-quotes as layout anchors |
| **Retro-Futurist** | Scanlines, phosphor greens/ambers, monospace terminals, CRT glow effects |
| **Luxury / Refined** | Tight letter-spacing, gold/cream palette, minimal but perfectly spaced, whisper-quiet animations |
| **Maximalist Chaos** | Dense information, overlapping layers, clashing complementary colors, controlled visual noise |
| **Toy / Playful** | Bold primaries, thick outlines, rounded everything, bouncy spring transitions |

**Rule**: Pick ONE direction. Name it in a comment at the top of your component.
Mixed aesthetics = no aesthetic. Commit and execute with precision.

---

## I. Typography as Architecture

Typography is the single highest-leverage design decision. Get this wrong and nothing else matters.

### Font Selection
Never use Inter, Roboto, Arial, or system fonts. Choose characterful faces:

| Role | Options |
|---|---|
| **Impact / Display Sans** | Syne, Clash Display, Cabinet Grotesk, Bebas Neue, Cal Sans |
| **Elegant Serif** | Cormorant Garamond, Playfair Display, DM Serif Display, Fraunces |
| **Mono / Technical** | JetBrains Mono, Fragment Mono, Space Mono, Geist Mono |
| **Humanist / Body** | Satoshi, General Sans, DM Sans, Instrument Sans |

Load from Google Fonts or Fontsource. Always declare a specific fallback stack.

### Typographic Hierarchy
```css
/* Display — creates drama */
.display {
  font-size: clamp(3rem, 10vw, 9rem);
  line-height: 0.9;
  letter-spacing: -0.04em;
  font-weight: 800;
}

/* Caption / Label — creates rhythm contrast */
.label {
  font-size: 0.7rem;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  font-weight: 500;
}
```

**Extreme scale contrast** between display and body is what separates designed work from
generated work. The ratio should feel almost too large.

### Fluid Typography
Never use fixed `px` breakpoints for type. Use `clamp()`:
```css
font-size: clamp(1rem, 2.5vw + 0.5rem, 1.375rem);
```

---

## II. Color & Atmosphere

### The Anti-Plastic Palette
Replace pure values with their perceptually richer equivalents:

| Instead of | Use |
|---|---|
| `#ffffff` | `#FAF9F6` (warm white) or `#F5F5F0` (cool linen) |
| `#000000` | `#0A0A0B` (deep charcoal) or `#111110` (warm black) |
| `#f5f5f5` | `#EFEDE8` (aged paper) |

Dominant colors with **one sharp accent** outperform even palettes.
Use CSS custom properties for every color decision:
```css
:root {
  --bg: #0A0A0B;
  --surface: #141414;
  --text: #E8E6E1;
  --accent: #C8F04A; /* one vivid accent only */
  --muted: #555550;
}
```

### Grain Overlay (Anti-Plastic Texture)
Add this to any flat background to break the "digital plastic" feel:
```css
.grain::after {
  content: '';
  position: fixed;
  inset: 0;
  background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='noise'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23noise)' opacity='1'/%3E%3C/svg%3E");
  opacity: 0.04;
  pointer-events: none;
  z-index: 9999;
}
```

### Layered Shadows
Never use a single flat shadow. Stack 3-4 layers:
```css
box-shadow:
  0 1px 2px rgba(0,0,0,0.07),
  0 4px 8px rgba(0,0,0,0.07),
  0 12px 24px rgba(0,0,0,0.08),
  0 32px 48px rgba(0,0,0,0.05);
```

---

## III. Spatial Composition

### Break the Grid Intentionally
```css
/* Uneven asymmetric grid — creates visual tension */
.layout {
  display: grid;
  grid-template-columns: 1fr 2.5fr 1.2fr;
  gap: clamp(1rem, 3vw, 3rem);
}

/* Editorial bleed — element escapes its container */
.hero-image {
  margin-left: calc(-1 * clamp(1rem, 5vw, 4rem));
  width: calc(100% + clamp(1rem, 5vw, 4rem));
}
```

### Spacing Tokens
Build spacing on a scale, not arbitrary `px` values:
```css
:root {
  --space-xs: 0.25rem;
  --space-sm: 0.5rem;
  --space-md: 1rem;
  --space-lg: 2rem;
  --space-xl: 4rem;
  --space-2xl: 8rem;
  --space-3xl: clamp(4rem, 10vw, 12rem);
}
```

### Negative Space as a Design Element
Swiss and editorial designs use negative space aggressively.
If a section feels empty, that's a feature — don't fill it.

---

## IV. Motion & Interaction

### Choreographed Entrance
Stagger reveals so elements appear in sequence, not simultaneously:
```css
.card:nth-child(1) { animation-delay: 0ms; }
.card:nth-child(2) { animation-delay: 80ms; }
.card:nth-child(3) { animation-delay: 160ms; }

@keyframes rise {
  from { opacity: 0; transform: translateY(16px); }
  to   { opacity: 1; transform: translateY(0); }
}
.card { animation: rise 0.5s cubic-bezier(0.22, 1, 0.36, 1) both; }
```

### Spring Physics (React / Framer Motion)
```tsx
import { motion } from 'framer-motion';

const spring = { type: 'spring', stiffness: 300, damping: 28 };

<motion.div
  initial={{ opacity: 0, y: 20 }}
  animate={{ opacity: 1, y: 0 }}
  transition={spring}
/>
```

### Weighted Button Micro-interactions
Buttons should feel physical — they compress, shift, and respond:
```css
.btn {
  transition: transform 80ms ease, box-shadow 80ms ease;
}
.btn:hover {
  transform: translateY(-2px);
  box-shadow: 0 8px 20px rgba(0,0,0,0.2);
}
.btn:active {
  transform: scale(0.97) translateY(1px);
  box-shadow: 0 2px 6px rgba(0,0,0,0.15);
}
```

### Respect Motion Preferences
Always wrap animations in:
```css
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    transition-duration: 0.01ms !important;
  }
}
```

---

## V. The Anti-Slop Checklist

Run through this before finalizing any UI. Every "NO" is a red flag:

**Forbidden defaults:**
- ❌ Purple/blue generic gradient on pure white
- ❌ `border-radius: 4px` (use 0 for industrial or 24px+ for organic)
- ❌ Centered hero with stock-photo background and "Get Started" CTA
- ❌ Inter, Roboto, or system-ui as the display font
- ❌ Equal-weight grid columns (`1fr 1fr 1fr`)
- ❌ Single flat `box-shadow`
- ❌ Pure `#000000` or `#ffffff`
- ❌ Icons from generic SVG blobs (use Lucide or Radix)

**Required qualities:**
- ✅ One "Hero Visual" — the unforgettable element (massive type, custom cursor, noise texture, etc.)
- ✅ Named aesthetic direction committed to consistently
- ✅ Fluid type with `clamp()` — no fixed breakpoints
- ✅ Motion that feels physics-based, not mechanical
- ✅ CSS custom properties for all colors, spacing, and type

---

## VI. Accessibility (Non-Negotiable)

Visual richness and accessibility are not in conflict. Both are required:

```css
/* Minimum contrast: 4.5:1 for body text, 3:1 for large text */
/* Test with: https://webaim.org/resources/contrastchecker/ */

/* Focus rings — don't remove, redesign them */
:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 3px;
  border-radius: 2px;
}
```

- Use semantic HTML (`<nav>`, `<main>`, `<article>`, `<button>`, not `<div>` for everything)
- All images need `alt` text; decorative images get `alt=""`
- Interactive elements need visible focus states
- Color alone should never convey meaning

---

## VII. Technical Stack

Default stack (override only if user specifies):

| Layer | Default | Alternatives |
|---|---|---|
| **Framework** | React (Vite) | Next.js, SvelteKit, Vue 3, plain HTML |
| **Styling** | Tailwind CSS + CSS custom properties | CSS Modules, vanilla CSS |
| **Animation** | Framer Motion (React) / CSS keyframes | GSAP, Motion One |
| **Icons** | Lucide React | Radix Icons, Heroicons |
| **Fonts** | Google Fonts via `@import` | Fontsource npm packages |

### Tailwind + CSS Variables Bridge
Use CSS variables for design tokens, Tailwind for layout/spacing utilities:
```css
/* globals.css */
:root { --accent: #C8F04A; --bg: #0A0A0B; }
```
```tsx
{/* Use arbitrary values to bridge */}
<div className="bg-[var(--bg)] text-[var(--accent)]" />
```

---

## VIII. Output Standards

- Write **complete, runnable code** — no `// ... rest of component` placeholders
- State the aesthetic direction in a top comment: `// Aesthetic: Neo-Brutalist`
- For multi-file output, show path at top of each file: `// src/components/Hero.tsx`
- Use CSS custom properties for every repeated color, spacing, or timing value
- Mobile-first: base styles are mobile, `md:` and `lg:` modifiers layer on top
- Include hover, focus, and active states for all interactive elements

---

## Reference Files

Load these for deeper domain guidance when relevant:

- `references/animation-patterns.md` — scroll-triggered reveals, page transitions, complex choreography
- `references/component-patterns.md` — nav, cards, modals, forms, data tables done right
- `references/color-systems.md` — building full design token systems, dark mode architecture
- `references/tailwind-advanced.md` — custom plugins, `@layer`, arbitrary values, JIT tricks

_(Load only the reference relevant to the current task.)_