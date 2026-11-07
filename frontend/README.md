# Frontend — Election Management & Voting System

Vue 3 + TypeScript single-page application for voters, administrators and auditors.

## Run

```bash
npm install
npm run dev        # http://localhost:5173
```

Vite proxies `/api` to `http://127.0.0.1:8770`, so start the backend first.

## Structure

```
src/
├── api.ts              typed REST client, error normalisation
├── router.ts           routes and sign-in guard
├── main.ts             app bootstrap
├── App.vue             shell: top bar, navigation, footer
├── stores/auth.ts      Pinia session state
├── composables/
│   └── useTurnout.ts   SSE subscription for turnout
├── styles/
│   └── tokens.css      design tokens: colour, type, spacing, radii, shadows
├── style.css           base styles and shared components
├── views/
│   ├── LoginView.vue       sign in and register
│   ├── ElectionsView.vue   election list
│   ├── BallotView.vue      ballot and receipt
│   ├── ReceiptView.vue     receipt verification
│   └── AdminView.vue       admin console
└── assets/
    └── hkmu-logo.png
```

## Conventions

- All fields crossing the network boundary are `snake_case`; local variables may be `camelCase`.
- Every component reaches the network through `api.ts`, never with a raw `fetch`.
- Design values come from the tokens in `styles/tokens.css`. No hard-coded colours or spacing.
- Accessibility: visible focus rings, keyboard operation, `prefers-reduced-motion` respected.

## Build

```bash
npm run build      # type-check plus production bundle
npm run preview    # serve the built bundle
```
