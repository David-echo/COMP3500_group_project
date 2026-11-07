# Frontend and Backend Integration Guide

> COMP 3500SEF / 8500SEF — Software Engineering, group project
> This is the contract between the frontend and the backend. Freeze it before parallel work starts.

---

## 1. Two rules

1. **The backend is the single source of truth for field names.** The frontend follows it and never
   renames fields for its own convenience.
2. **Every field uses `snake_case`.** This includes REST bodies, query parameters and SSE payloads.
   A single convention with no exceptions.

---

## 2. Field names

| Meaning | Correct | Forbidden |
|---|---|---|
| Election identifier | `election_id` | `electionId`, `electionID` |
| Position identifier | `position_id` | `positionId` |
| Candidate index | `candidate_idx` | `candidateIndex` |
| Winning index | `winner_idx` | `winnerIndex` |
| Turnout | `turnout` | `voteRate`, `percent` |
| Receipt code | `code` | `receiptCode` |

The frontend keeps its own `camelCase` variables if it wants, but converts at the boundary in
`api.ts`. It must never send `camelCase` in a request.

---

## 3. Response shapes

### Success

Return the business object directly. Do not wrap it in `{ code, data, msg }`.

```json
{ "id": 1, "title": "2026 Student Union Chairperson Election", "status": "open" }
```

Lists return arrays directly.

### Failure

Every failure returns the same shape, and **`detail` is always a string**:

```json
{ "detail": "You have already voted and cannot vote again" }
```

Never return an array or an object. FastAPI's default validation error is an array of objects;
the backend flattens it in a global exception handler, so the frontend never has to render
`[object Object]`.

### Status codes

| Code | Meaning | Frontend behaviour |
|---|---|---|
| 200 / 201 | success | render the data |
| 400 | malformed request | show the message |
| 401 | not signed in or token expired | clear the session and go to the sign-in page |
| 403 | signed in but not allowed | show "you do not have permission" |
| 404 | not found | show "not found" |
| 409 | conflict, such as duplicate vote | show the message as a warning |
| 422 | validation failed | show the message, highlighting the field |

---

## 4. Time

- All timestamps are ISO 8601 strings in UTC, for example `2026-11-05T15:52:53`.
- The frontend converts to local time for display and truncates to seconds.
- **Clients never decide whether voting is open by comparing timestamps.** They read `status`.
  The server compares timestamps only to advance the state.

---

## 5. SSE

### Endpoint

```
GET /api/v1/events/turnout?election_id=1
```

### Message format

```
event: turnout
data: {"election_id":1,"voted":20,"total":30,"percent":66.7}

```

The field names follow the same convention as REST.

### Rules

- The first frame must be sent immediately so the client knows the connection is alive.
- A comment line heartbeat every 15 seconds keeps proxies from closing an idle connection.
- **Results are not pushed while voting is open.** Only the aggregate turnout is sent.
- The client reconnects automatically; `EventSource` does this by default.

---

## 6. Frontend conventions

- One `api.ts` for all requests: it sets the base URL, attaches the token and normalises errors.
- One `ApiError` type carrying `status` and `message`.
- A 401 handler clears the session and redirects to sign-in.
- All request and response types are TypeScript interfaces in `api.ts`, matching the backend
  schemas.

---

## 7. Checklist before merging frontend work

- [ ] No `camelCase` field appears in any request body or query parameter
- [ ] Every error path shows `detail` as a string, never `[object Object]`
- [ ] A 401 sends the user back to sign-in
- [ ] Times are displayed to seconds, in local time
- [ ] Status is read from `status`, never recomputed from timestamps
- [ ] SSE reconnects after a dropped connection and the indicator reflects it
