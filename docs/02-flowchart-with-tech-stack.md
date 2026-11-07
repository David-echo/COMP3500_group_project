# System Flows and Technology Stack

> COMP 3500SEF / 8500SEF — Software Engineering, group project
> Topic: Election Management and Voting System

Five diagrams at increasing levels of detail. The first two are for a general audience, the last
three for developers and for the architecture chapter.

---

## 0. Overview: process and technology in one picture

```mermaid
flowchart TB
    subgraph BROWSER["In the browser (Vue 3 + TypeScript)"]
        direction TB
        L["Sign-in page<br/>student ID and password"]
        E["Election list<br/>cards, status, turnout"]
        B["Ballot page<br/>select and confirm"]
        R["Receipt page<br/>code and verification"]
    end

    subgraph SERVER["On the server (Python + FastAPI)"]
        direction TB
        AUTH["Authentication<br/>JWT and bcrypt"]
        SVC["Business logic<br/>state machine, voting transaction<br/>tallying, audit chain"]
        PUSH["Real-time push<br/>SSE, turnout only"]
    end

    subgraph DATA["Data"]
        direction TB
        PG[("PostgreSQL<br/>ballots, vote records, receipts<br/>audit log")]
        RD[("Redis<br/>sessions and pub/sub")]
    end

    L -->|POST /auth/login| AUTH
    E -->|GET /elections| SVC
    B -->|POST /votes| SVC
    R -->|GET /receipts/code| SVC
    PUSH -.->|turnout updates| E
    AUTH --> PG
    SVC --> PG
    SVC --> RD
    PUSH --> RD
```

Reading order: the voter acts in the browser, the request reaches the server over HTTPS, the
business logic runs inside a database transaction, and results come back over REST or SSE.

---

## 1. Technology stack by layer

```mermaid
flowchart LR
    subgraph U["User layer"]
        U1["Voter<br/>student"]
        U2["Administrator"]
        U3["Auditor"]
    end

    subgraph P["Presentation layer, in the browser"]
        P1["Vue 3 component<br/>TypeScript"]
        P2["Pinia state<br/>session and elections"]
        P3["Vue Router<br/>navigation"]
        P4["ECharts<br/>result charts"]
        P5["EventSource<br/>SSE subscription"]
    end

    subgraph C["Communication layer"]
        C1["Axios<br/>REST over HTTPS"]
        C2["FastAPI router<br/>request validation"]
        C3["Pydantic v2<br/>request and response models"]
        C4["JWT<br/>authentication dependency"]
    end

    subgraph A["Application layer"]
        A1["Voting service<br/>cast_ballot"]
        A2["State machine<br/>scheduled, open, closed, published"]
        A3["Tally strategies<br/>FPTP, IRV"]
        A4["Audit chain<br/>append and verify"]
        A5["Result service<br/>aggregate and digest"]
    end

    subgraph D["Data layer"]
        D1["SQLAlchemy 2.0<br/>async ORM"]
        D2[("PostgreSQL 16<br/>transactions and constraints")]
        D3[("Redis 7<br/>cache and pub/sub")]
        D4["Alembic<br/>migrations"]
    end

    U1 --> P1
    U2 --> P1
    U3 --> P1
    P1 --> P2
    P1 --> P3
    P1 --> P4
    P1 --> P5
    P2 --> C1
    P3 --> C1
    C1 -->|HTTPS| C2
    C2 --> C3
    C2 --> C4
    C2 --> A1
    C2 --> A2
    C2 --> A5
    A1 --> A2
    A1 --> A4
    A1 --> A3
    A5 --> A3
    A1 --> D1
    A4 --> D1
    D1 --> D2
    A5 --> D3
    C4 --> D3
    D4 -.-> D2
```

Reading order: from users down to the database, every level names the concrete language and
framework, so you can answer "what is used for what".

---

## 2. Main voting flow, step by step

```mermaid
flowchart TD
    S1["Voter opens the site<br/>Vue 3"]
    S2["Sign in<br/>Vue form to Axios to FastAPI /auth/login"]
    S3["Server verifies the password<br/>bcrypt, then issues a JWT"]
    S4["Frontend stores the token<br/>Pinia plus localStorage"]
    S5["Load the election list<br/>GET /elections, filtered by voter roll"]
    S6["Select an election<br/>route to the ballot page"]
    S7["Server checks the state<br/>state machine: is it open"]
    S8["Load candidates<br/>Pydantic response model"]
    S9["Select a candidate<br/>component state"]
    S10["Confirm<br/>second step to avoid a misclick"]
    S11["POST /votes<br/>single transaction begins"]
    S12{"Status open, on the roll,<br/>not already voted?"}
    S13["Rejected<br/>409 or 403 with a message"]
    S14["Write the ballot and the vote record<br/>unique constraint arbitrates"]
    S15["Create the receipt<br/>and append the audit entry"]
    S16["Commit<br/>return the receipt code"]
    S17["Show the receipt<br/>copy button"]
    S18["Optional verification<br/>GET /receipts/code"]
    S19["Turnout updates<br/>SSE pushes the aggregate only"]
    S20(["Done"])

    S1 --> S2 --> S3 --> S4 --> S5 --> S6 --> S7
    S7 -->|not open| S13
    S7 -->|open| S8 --> S9 --> S10 --> S11 --> S12
    S12 -->|no| S13
    S12 -->|yes| S14 --> S15 --> S16 --> S17 --> S18 --> S20
    S16 -.-> S19
    S13 --> S8
```

---

## 3. Inside the vote transaction

This is the diagram the architecture chapter uses. It shows exactly what the backing transaction
does and where the guarantees come from.

```mermaid
sequenceDiagram
    autonumber
    actor V as Voter
    participant FE as Vue 3
    participant RT as FastAPI router
    participant SV as Voting service
    participant DB as PostgreSQL

    V->>FE: press confirm
    FE->>RT: POST /api/v1/elections/id/votes with JWT
    RT->>RT: decode JWT, load the user
    RT->>RT: Pydantic validates the body
    RT->>SV: cast_ballot user, election_id, choice
    SV->>DB: BEGIN transaction
    SV->>DB: load the election row
    DB-->>SV: status and tally method
    SV->>SV: state machine check
    alt not open
        SV-->>RT: ElectionNotOpen
        RT-->>FE: 409 with a message
    else open
        SV->>DB: load the voter roll entry
        DB-->>SV: eligible flag
        SV->>DB: insert into ballots, anonymous
        DB-->>SV: ballot id
        SV->>DB: insert into votes_log
        alt unique constraint violated
            DB-->>SV: IntegrityError
            SV->>DB: ROLLBACK
            SV-->>RT: duplicate vote
            RT-->>FE: 409 already voted
        else inserted
            SV->>DB: insert the receipt
            SV->>DB: update voter_roll
            SV->>DB: append the audit entry with the previous hash
            SV->>DB: COMMIT
            SV-->>RT: receipt code
            RT-->>FE: 201 with the code
            FE-->>V: show the receipt
        end
    end
```

The guarantee comes from three places, in this order:

1. **The state machine** decides whether voting is allowed at all.
2. **The unique constraint** decides whether this voter has already voted; no application-level
   check is involved.
3. **The audit chain** makes after-the-fact tampering detectable.

---

## 4. Deployment topology

```mermaid
flowchart TB
    subgraph CLIENT["Client"]
        B1["Browser<br/>Vue 3 single-page application"]
    end

    subgraph EDGE["Edge"]
        N1["Nginx<br/>TLS termination and static files"]
    end

    subgraph APP["Application tier"]
        A1["Uvicorn workers<br/>FastAPI"]
        A2["Uvicorn workers<br/>FastAPI"]
    end

    subgraph DATATIER["Data tier"]
        D1[("PostgreSQL<br/>primary")]
        D2[("PostgreSQL<br/>read replica, optional")]
        R1[("Redis<br/>sessions and pub/sub")]
    end

    B1 -->|HTTPS| N1
    N1 -->|/api| A1
    N1 -->|/api| A2
    A1 --> D1
    A2 --> D1
    D1 -.->|streaming replication| D2
    A1 --> R1
    A2 --> R1
```

For a single-machine demonstration, Nginx and the extra worker are omitted and everything runs
locally; the diagram shows the target shape.

---

## 5. Quick reference for the presentation

| Question | Answer |
|---|---|
| Frontend language | TypeScript, built with Vue 3 |
| Backend language | Python 3.11, FastAPI |
| Database | PostgreSQL 16, with SQLite fallback |
| Cache | Redis 7, used for sessions and pub/sub |
| How does real-time work | SSE, server push, one-way |
| How is one vote per voter enforced | database unique constraint on position and user |
| How is anonymity preserved | ballots and voter roll are separate tables with no linking key |
| What are the tally methods | FPTP now, IRV added by strategy pattern |
| How is tampering detected | append-only audit chain with hashes |
| How many tests | 44, including concurrency and tamper cases |

---

## 6. Where each member plugs in

| Member | Owns | Points at in this document |
|---|---|---|
| 1 | Process and planning | sections 0 and 2 |
| 2 | Requirements | sections 2 and 3 |
| 3 | Modelling | sections 3 and 4 |
| 4 | Architecture | sections 1, 4 and 5 |
| 5 | Backend implementation | sections 1 and 3 |
| 6 | Frontend implementation | sections 0 and 2 |
| 7 | Testing and evolution | sections 3 and 5 |
