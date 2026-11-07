# Software Requirements Specification

> Project: Election Management and Voting System
> Course: COMP 3500SEF / 8500SEF
> Version 0.1 · Author · Date

Follow the document structure from Lecture 4. Use `shall` for mandatory requirements and `should`
for desirable ones, and give a rationale for each requirement.

---

## 1. Preface

### 1.1 Purpose

Who this document is for: the development team, the course assessor, and a future maintainer.

### 1.2 Scope

What the system does and, just as importantly, what it does not do.

### 1.3 Definitions

| Term | Meaning |
|---|---|
| Election | one ballot event with a fixed opening and closing time |
| Position | a seat being filled within an election |
| Candidate | a person or option standing for a position |
| Ballot | an anonymous record of a choice |
| Voter roll | the list of voters eligible for an election |
| Receipt | a code the voter keeps to confirm the ballot was counted |
| State machine | the four states and the transitions between them |
| IRV | instant runoff voting, also called ranked choice |

---

## 2. Introduction

### 2.1 Background

Why the system exists and what problem it solves.

### 2.2 Overall description

Two or three paragraphs: who uses it, what it replaces, and the central design tension between
anonymity and auditability.

---

## 3. User requirements

| ID | Actor | Requirement | Rationale | Priority |
|---|---|---|---|---|
| UR-1 | Voter | I want to vote without anyone learning my choice | protects the voter from pressure | must |
| UR-2 | Voter | I want to confirm my ballot was counted | confidence in the result | must |
| UR-3 | Administrator | I want to control when voting opens and closes | controls the process | must |
| UR-4 | Auditor | I want to verify no ballot was altered | accountability | must |

---

## 4. System architecture

Short summary plus a reference to the layered diagram in the project plan. Name the four layers,
the technology in each, and why the system is a transaction processing system.

---

## 5. System requirements

### 5.1 Functional requirements

| ID | Requirement | Verification |
|---|---|---|
| FR-1 | The system shall authenticate a voter with a student ID and password | API test |
| FR-2 | The system shall allow a voter to cast exactly one ballot per position | concurrency test |
| FR-3 | The system shall reject a ballot when the election is not open | API test |
| FR-4 | The system shall issue a receipt that does not contain the choice | inspection plus test |
| FR-5 | The system shall allow an administrator to move the state forward only | state machine test |

### 5.2 Non-functional requirements

Every non-functional requirement must be measurable. Write the number, not an adjective.

| ID | Requirement | How it is verified |
|---|---|---|
| NFR-1 | Voting endpoint p95 shall be under 300 ms at 100 concurrent voters | load test |
| NFR-2 | Eight concurrent submissions by the same voter shall result in exactly one accepted ballot | concurrency test |
| NFR-3 | A single modified audit record shall be detected 100 percent of the time | tamper test |
| NFR-4 | Ballots, vote records and receipts shall never differ by more than zero | invariant check |
| NFR-5 | The interface shall meet WCAG AA contrast for body text | inspection |
| NFR-6 | The system shall recover from a Redis outage by falling back to in-process pub/sub | failure test |

Bad examples, for contrast: "the system shall be fast", "the system shall be secure". Neither can
be tested.

---

## 6. System models

- Use case diagram and use case tables
- Sequence diagram for casting a vote
- State machine for the election lifecycle
- Domain class diagram

---

## 7. System evolution

Planned changes and the assumptions that could invalidate the design.

---

## 8. Appendices

Database design, interface list, and the mapping from requirements to test cases.
