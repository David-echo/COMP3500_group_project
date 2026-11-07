# API Contract

> This file is the agreement between the frontend and the backend. Change it before changing code,
> not after.

---

## 1. Conventions

- Base path: `/api/v1`
- Content type: `application/json`
- Field naming: `snake_case` everywhere, including SSE
- Authentication: `Authorization: Bearer <token>`
- Errors: `{ "detail": "<string>" }`, always a string

---

## 2. Endpoints

### `POST /auth/login`

Request

```json
{ "student_id": "HK100000", "password": "voter12345" }
```

Response 200

```json
{ "access_token": "...", "token_type": "bearer", "role": "VOTER", "name": "Chan Ka-ho" }
```

Errors: 401 wrong credentials, 422 validation failed.

---

### `GET /elections`

Response 200: an array of elections. Each item contains `id`, `title`, `status`,
`status_label`, `opens_at`, `closes_at`, `tally_method`, `my_vote_status`, `positions`, `turnout`.

---

### `POST /elections/{id}/votes`

Request

```json
{ "position_id": 1, "choice": [0] }
```

Response 201

```json
{ "receipt_code": "ABCD-1234-EFGH", "audit_seq": 42 }
```

Errors: 403 not on the roll, 409 already voted, 409 election not open, 422 invalid candidate index.

---

### `GET /receipts/{code}`

Response 200

```json
{ "election_title": "...", "cast_at": "2026-11-05T15:52:53", "counted": true }
```

The response never includes the choice.

---

### `GET /elections/{id}/results`

Response 200 when published, 200 with `published: false` and a message when still open.

---

### `GET /events/turnout?election_id=1`

Server-sent events. Frame:

```
event: turnout
data: {"election_id":1,"voted":20,"total":30,"percent":66.7}
```

---

## 3. Change log

| Date | Change | Reason | Affected clients |
|---|---|---|---|
| | | | |
