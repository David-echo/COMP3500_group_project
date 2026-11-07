# Election Management & Voting System

> COMP 3500SEF / 8500SEF — Software Engineering, group project
> Topic 2: Election Management and Voting System

A **runnable, testable and auditable** election system. The engineering focus is not the interface —
it is resolving the central tension in any election system:

> **Anonymity requires that no one can trace a ballot back to a voter.
> Auditability requires that cheating can be detected. These two demands conflict.**

We satisfy both with **data structure** and **database constraints**, rather than by promising
"we will not read the logs".

---

## 1. Technology stack

| Layer | Technology | Notes |
|---|---|---|
| Frontend | **Vue 3 + TypeScript** | Vite · Pinia · Vue Router · ECharts · Axios |
| Real-time | **SSE (Server-Sent Events)** | browser `EventSource` ↔ FastAPI `StreamingResponse` |
| Backend | **Python 3.11+ + FastAPI** | Pydantic v2 · SQLAlchemy 2.0 (async) · Uvicorn |
| Database | **PostgreSQL 16** | unique constraints and transactions guarantee one vote per voter |
| Cache | **Redis 7** | sessions · caching · SSE fan-out across instances |

> Without PostgreSQL / Redis the app falls back to **SQLite + in-process pub/sub**.
> Behaviour is identical; only multi-instance deployment is unavailable. Switching is a one-line
> change in `.env`.

---

## 2. Quick start

### Backend (no database server required)

```bash
cd backend
pip install -r requirements.txt
python -m app.seed                    # generate demo data
uvicorn app.main:app --reload --port 8770
```

- Interactive API documentation: **http://127.0.0.1:8770/docs**

### Frontend

```bash
cd frontend
npm install
npm run dev                           # http://localhost:5173
```

Vite proxies `/api` to `127.0.0.1:8770`, so open port 5173 and no CORS configuration is needed.

### Demo accounts

| Role | Student ID | Password |
|---|---|---|
| Administrator | `ADMIN001` | `admin12345` |
| Auditor | `AUDIT001` | `audit12345` |
| Voter | `HK100000` – `HK100029` (30 accounts) | `voter12345` |

### Switching to PostgreSQL + Redis

```bash
docker compose up -d                  # PostgreSQL 16 + Redis 7
cp .env.example .env                  # edit DATABASE_URL and REDIS_URL
cd backend && python -m app.seed
```

---

## 3. Repository layout

```
.
├── backend/                  FastAPI service
│   ├── app/
│   │   ├── main.py             application assembly (no business logic)
│   │   ├── config.py           the only place that reads environment variables
│   │   ├── db.py               async engine and session factory
│   │   ├── models.py           ORM models and unique constraints
│   │   ├── schemas.py          Pydantic request/response models (auto OpenAPI)
│   │   ├── security.py         bcrypt, JWT, AES-GCM ballot encryption
│   │   ├── deps.py             authentication and role dependencies
│   │   ├── domain/             state machine, hash chain, tally strategies
│   │   ├── services/           voting, results, audit, pub/sub
│   │   ├── api/                auth, elections, votes, results, audit, events
│   │   └── seed.py             demo dataset
│   ├── tests/                  44 automated tests
│   └── requirements.txt
├── frontend/                 Vue 3 + TypeScript
│   └── src/
│       ├── views/              four-step flow plus admin console
│       ├── stores/             Pinia authentication state
│       ├── composables/        SSE subscription
│       ├── styles/             design tokens
│       └── api.ts              typed REST client
├── docs/                     project documentation
│   ├── 01-project-plan.md      process, feature breakdown, technology choice
│   ├── 02-flowchart-with-tech-stack.md
│   ├── 03-api-integration-guide.md
│   ├── diagrams/               rendered diagrams (simple and detailed)
│   └── templates/              SRS, ADR, API contract, meeting minutes
├── docker-compose.yml        PostgreSQL + Redis
└── .env.example
```

---

## 4. Two core design decisions

### 4.1 Anonymity: ballots and the voter roll are physically separated

```
voter_roll   who voted      user_id / has_voted      no ballot_id
ballots      what was cast  anon_id / choice_enc     no user_id
receipts     proof          code → given to the voter only
votes_log    one vote       UNIQUE(position_id, user_id)
```

There is **no field or foreign key** anywhere that can link a voter to a choice.
Anonymity is not a promise, it is a property of the schema — and the tests assert that the
linking columns do not exist.

### 4.2 One vote per voter: arbitrated by a **database unique constraint**

The vote transaction does **not** read `has_voted` and then insert (check-then-act, which allows a
double vote under concurrency). It inserts into `votes_log`, which carries
`UNIQUE(position_id, user_id)`, and lets the database arbitrate.

A concurrency test submits the same ballot eight times in parallel: **exactly one succeeds**.

---

## 5. Constraints on real-time updates

| Channel | Content | When it may be pushed |
|---|---|---|
| `/api/v1/events/turnout` | turnout (aggregate) | while voting is open |
| `/api/v1/events/results` | per-candidate counts | **only after the election closes** |

> Real elections do not publish running totals while voting is open: doing so influences later
> voters and undermines fairness. This is recorded as domain requirement DR-1, and the backend
> simply does not expose the counts until the election is closed.

---

## 6. Testing

```bash
cd backend
pytest -q                        # 44 tests
pytest tests/test_api.py -q      # API and integration tests
```

| Level | Coverage |
|---|---|
| Domain | every state transition, FPTP and IRV tallying, hash-chain tamper and deletion detection |
| API | login, voting, duplicate vote, receipt verification, lifecycle gating, authorisation |
| Invariants | ballots == vote records == receipts |
| Concurrency | concurrent duplicate votes: exactly one succeeds |
| SSE | protocol headers, first frame, pub/sub delivery |

---

## 7. API summary (full reference at `/docs`)

| Method | Path | Description |
|---|---|---|
| POST | `/api/v1/auth/register` | register |
| POST | `/api/v1/auth/login` | sign in, returns a JWT |
| GET | `/api/v1/auth/me` | current user |
| GET | `/api/v1/elections` | elections visible to the caller |
| POST | `/api/v1/elections` | create an election (admin) |
| PATCH | `/api/v1/elections/{id}/status` | change status (state machine only) |
| POST | `/api/v1/elections/{id}/votes` | cast a vote |
| GET | `/api/v1/receipts/{code}` | verify a receipt (never reveals the choice) |
| GET | `/api/v1/elections/{id}/results` | results (only after closing) |
| POST | `/api/v1/elections/{id}/results/publish` | tally and publish (admin) |
| GET | `/api/v1/elections/{id}/integrity` | invariant checks |
| GET | `/api/v1/audit/verify` | verify the audit hash chain |
| GET | `/api/v1/events/turnout` | SSE: turnout |
| GET | `/api/v1/events/results` | SSE: results (after closing only) |

---

## 8. Honest statement of guarantees

- **Ballot encryption** is application-level AES-GCM. It prevents someone with read-only database
  access from seeing a voter's choice. It is **not** end-to-end verifiable encryption
  (such as homomorphic tallying) and we do not claim the cryptographic strength of a national
  election system.
- The **hash chain** can only **detect** tampering. It cannot stop an attacker who recomputes the
  entire chain — unless the chain tip is published externally as an anchor.
- Authentication uses JWT. A real election would additionally require multi-factor authentication
  and hardware tokens.
- A production deployment must enable HTTPS, use a production ASGI server configuration and
  disable `/docs`.
