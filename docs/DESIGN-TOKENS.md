# Design Tokens — Consilium UI system

The tokens `frontend/index.html` is built on. Fonts load from Google Fonts; all CSS/JS stay
inline in the single-file frontend, and any images are embedded as data URIs.

**Font link:**
```html
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,500;12..96,600;12..96,700;12..96,800&family=Figtree:wght@400;500;600;700&family=JetBrains+Mono:wght@500;700&display=swap">
```

**Tokens (3-state theme: bare `:root` light · `prefers-color-scheme` dark guarded ·
`[data-theme]` override):**
```css
:root{
  --ground:#FBF6F0; --surface:#FFFFFF; --surface-2:#F6EDE3; --surface-3:#F1E5D7;
  --ink:#23201C; --ink-soft:#5C554C; --muted:#948A7D; --line:#E8DCCD;
  --coral:#FF5D3A; --coral-2:#E5482A; --coral-tint:#FFEBE4;   /* accent */
  --teal:#0E6E6C; --teal-tint:#E0F0EF;
  --amber:#D9880C; --amber-tint:#FBEFD6;
  --good:#2E9E6B; --crit:#D64545;                              /* semantic (stance) */
  --shadow:0 1px 2px rgba(45,32,20,.05), 0 8px 24px -12px rgba(45,32,20,.18);
  --shadow-lg:0 2px 4px rgba(45,32,20,.06), 0 24px 60px -24px rgba(45,32,20,.30);
  --r:14px; --r-sm:10px; --r-lg:22px; --maxw:1180px;
  --c1:#E5482A; --c2:#0C8A83; --c3:#D9880C; --c4:#3E5FC0;      /* categorical */
  --chart-grid:#EFE6DA; --chart-axis:#948A7D; --chart-fill:#FCEAE4;
  --sans:"Figtree",-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
  --display:"Bricolage Grotesque",var(--sans);
  --mono:"JetBrains Mono",ui-monospace,"SF Mono",monospace;
}
:root:not([data-theme="light"]) , :root[data-theme="dark"]{  /* apply dark under both */
  --ground:#16120E; --surface:#211A14; --surface-2:#2A2119; --surface-3:#332820;
  --ink:#F4ECE1; --ink-soft:#C6BAAB; --muted:#8E8375; --line:#372B22;
  --coral:#FF6E4E; --coral-2:#FF8468; --coral-tint:#3A211A;
  --teal:#3FADA9; --teal-tint:#153433; --amber:#F0B23E; --amber-tint:#3A2C14;
  --good:#49B481; --crit:#E86A6A;
  --c1:#FF7458; --c2:#3FADA9; --c3:#F0B23E; --c4:#8AA0EE;
  --chart-grid:#2E241C; --chart-axis:#8E8375; --chart-fill:#31201A;
  --shadow:0 1px 2px rgba(0,0,0,.4), 0 10px 30px -14px rgba(0,0,0,.6);
  --shadow-lg:0 2px 6px rgba(0,0,0,.5), 0 28px 70px -24px rgba(0,0,0,.75);
}
```
*(Split the dark block into a `@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){...}}`
guard and a separate `:root[data-theme="dark"]{...}` override so an explicit theme toggle wins
both ways — see `frontend/index.html` for the exact pattern in place.)*

**Type roles:** display = Bricolage Grotesque (headings, the recommendation); body = Figtree; mono
= JetBrains Mono (figures, labels, agent names, trace timestamps).

**Stance chips (semantic, NOT the accent colour):** yes → `--good` · conditional → `--amber` ·
no → `--crit` · blocker → `--crit` on a stronger/filled treatment so it reads as the hardest stop.
The accent colour stays for brand/active UI, never for a stance.

## P3.6 card states (no new tokens)

The rules-trigger UI reuses existing tokens rather than adding any:

- **Triggered lane** — coral left rule (`--coral`) and the stance chip above (`--good` / `--amber` /
  `--crit`). Verified evidence quotes sit under a dashed `--line` divider in `--muted` 11px; seeded
  facts read "seeded" instead of a quote.
- **Not-triggered lane** — a neutral `--line` left rule at 85% opacity. "All rules checked — none
  tripped" is `--good`; "No rule triggered" is `--ink-soft`; "Couldn't check: …" is `--muted`.
- **Unclear tripwire** — `--amber` text on `--amber-tint`, 12px semibold: "Unclear: … — mentioned
  but not confirmed". Amber is deliberate: it is a caution (confirm before proceeding), not a stop.
- **System-governed** — blocker rules in the Council tab render as read-only `--muted` rows with a
  small bordered "system-governed" tag (`--line`), never an input.
- The words "skipped" and "no impact" are never used for a not-triggered agent.
