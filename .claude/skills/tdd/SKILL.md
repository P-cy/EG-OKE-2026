---
name: tdd
description: Test-driven development. Use when the user wants to build features or fix bugs test-first, mentions "red-green-refactor", or wants integration tests.
---

# Test-Driven Development

TDD is the red → green loop. This skill is the reference that makes that loop produce tests worth keeping: what a good test is, where tests go, the anti-patterns, and the rules of the loop. Every section applies on every cycle — consult them before and during the loop, not after.

When exploring the codebase, read `CONTEXT.md` (if it exists) so test names and interface vocabulary match the project's domain language, and respect ADRs in the area you're touching.

## What a good test is

Tests verify behavior through public interfaces, not implementation details. Code can change entirely; tests shouldn't. A good test reads like a specification — "user can checkout with valid cart" tells you exactly what capability exists — and survives refactors because it doesn't care about internal structure.

See [tests.md](tests.md) for examples and [mocking.md](mocking.md) for mocking guidelines.

## Seams — where tests go

A **seam** is the public boundary you test at: the interface where you observe behavior without reaching inside. Tests live at seams, never against internals.

**Test only at pre-agreed seams.** Before writing any test, write down the seams under test and confirm them with the user. No test is written at an unconfirmed seam. You can't test everything — agreeing the seams up front is how testing effort lands on the critical paths and complex logic instead of every edge case.

Ask: "What's the public interface, and which seams should we test?"

When the shape of that interface is itself in question — how deep the module is, where the seam belongs, what the interface should expose — use the `/codebase-design` skill for the vocabulary. It is the shared source of the module, interface, depth, seam, adapter, leverage and locality terms, and it is a reference to consult, not a session to run.

## Anti-patterns

- **Implementation-coupled** — mocks internal collaborators, tests private methods, or verifies through a side channel (querying the database instead of using the interface). The tell: the test breaks when you refactor but behavior hasn't changed.
- **Tautological** — the assertion recomputes the expected value the way the code does (`expect(add(a, b)).toBe(a + b)`, a snapshot derived by hand the same way, a constant asserted equal to itself), so it passes by construction and can never disagree with the code. Expected values must come from an independent source of truth — a known-good literal, a worked example, the spec.
- **Horizontal slicing** — writing all tests first, then all implementation. Bulk tests verify _imagined_ behavior: you test the _shape_ of things rather than user-facing behavior, the tests go insensitive to real changes, and you commit to test structure before understanding the implementation. Work in **vertical slices** instead — one test → one implementation → repeat, each test a **tracer bullet** that responds to what the last cycle taught you.

## Rules of the loop

- **Red before green.** Write the failing test first, then only enough code to pass it. Don't anticipate future tests or add speculative features.
- **One slice at a time.** One seam, one test, one minimal implementation per cycle.
- **Refactoring is not part of the loop.** It belongs to the review stage, not the red → green implementation cycle.
  (ในโปรเจกต์นี้ขั้นรีวิวคือ `/code-review` ที่มากับ Claude Code — สกิล `code-review` ของต้นทางไม่ได้ติดตั้งไว้ ดู [../README.md](../README.md))

## หมายเหตุสำหรับโปรเจกต์นี้

seam ที่ตกลงกันแล้วและมีเทสต์คุมอยู่ ดู [docs/13-testing-and-load.md](../../../docs/13-testing-and-load.md)

- **backend** — เรียก router function ตรงๆ ด้วย Mongo/Redis จริงจาก docker compose (ไม่ mock)
  `conftest.py` สลับ `settings.MONGO_DB` ไปฐาน `_test` ให้เอง
- **frontend** — vitest + jsdom; logic ล้วนอยู่ใน `src/lib/`, component แยกออกมาให้เทสต์ได้ที่ `src/components/`
- **contract ข้ามฝั่ง** — `backend/tests/test_api_contracts.py` อ่าน `frontend/src/lib/api.ts` จริง
  เพิ่ม endpoint ใหม่แล้วให้เพิ่มเคสที่นี่ด้วย บั๊กชื่อคีย์ไม่ตรงกันผ่าน type checker ทั้งสองฝั่ง
