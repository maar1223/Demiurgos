# Recovery-words rotation must prove ownership

**Feature id**: `words-rotation-requires-ownership`
**Branch**: `fix/words-rotation-requires-ownership`
**Status**: in progress
**Author decision**: fix it (reported by the author as a suspected bypass; confirmed).

## Finding (confirmed, security)

`POST /api/auth/credentials/words/rotate` requires **only an active session**. Its
three siblings in the same panel require the **recovery words** as the ownership
proof:

| Endpoint | Proof required | Evidence |
|---|---|---|
| `POST /credentials/password` (R-AC-05a) | session + words | `api_server.py:1705` |
| `POST /credentials/password/remove` (R-AC-05b) | session + words | `api_server.py:1725` |
| `POST /credentials/username` (R-AC-05c) | session + words | `api_server.py:1746` |
| `POST /credentials/words/rotate` (R-ERK-01) | **session only** | `api_server.py:1762-1766` |

`account_rotate_words` (`account.py:89`) takes no proof at all: it generates new
words and commits the new hash. The frontend `RotateWordsCard`
(`ProfilePage.tsx:656-697`) calls `rotateWords()` directly and is NOT wired to
`useRecoveryWordsUnlock`, unlike the Usuario/Contraseña tabs (`:353`, `:372`).

### The escalation chain (verified end to end)

`credentials_login` (`api_server.py:1576-1597`) authenticates with the
**password alone** — the words play no part in login. So:

```
know the password → session → /words/rotate → NEW words returned in plaintext
                                                     ↓
                     /username and /password ← those words satisfy the gate
```

The owner's old words are invalidated by the rotation, so the legitimate owner is
locked out of their own account. **A session is escalated to permanent
ownership.** `remember_me` grants a 30-day session (`:1583`), so a stolen cookie
or an unattended machine is enough.

### Why this is a design hole, not a typo

`test_api_auth.py:669` is literally named
`test_rotate_words_requires_an_active_session`, and `:675` asserts the session
alone returns the words. The old contract *is* the hole.

## Scope

### In scope
- `src/tools/demiurgos-suite/wiki/api_server.py` — the rotate endpoint.
- `frontend/src/api/wiki.ts` — `rotateWords` sends the words.
- `frontend/src/pages/ProfilePage.tsx` — `RotateWordsCard` becomes words-gated.
- Tests on both sides.
- Spec amendment recorded in this document.

### Out of scope — do NOT change
- The other three credential endpoints and their guards.
- `account_rotate_words`'s internals (generation + atomic commit).
- The vault lifecycle endpoints (`/vault/enable|disable|reauth-interval`).
- The session model, cookie flags, or TTLs.

## Fix

1. **Backend**: mirror `credentials_change_username` exactly — vault active → 403;
   no principal → 401; no account → 401; then
   `account_verify_words(payload.words, account["words_hash"], _words_rate_limiter)`
   → 401 on failure — and only then rotate. Add a `CredentialsRotateWordsRequest`
   model with `words: str`.
2. **Frontend**: `rotateWords(words: string)` sends `{ words }`.
3. **Frontend**: `RotateWordsCard` takes `unlockedWords` + `onUnlocked`, asks for
   the current words when locked (same UX as the other tabs), arms the session
   unlock on success, and shows the new words once as today. The words must never
   reach localStorage, sessionStorage or cookies (REQ-SRW-02).
4. **Tests**: rewrite the two tests that encode the old contract, and add a
   regression test for the chain (a session without words cannot rotate, and
   therefore cannot mint words to change credentials). Cover the locked and
   unlocked states of the card.

## Accepted consequence

If the author loses the words they can no longer rotate them. That is correct:
the words are the root of ownership, and the UI already says they are the only
way to recover the account. What must not happen is regenerating them from a
weaker credential.

## Spec amendment

**R-ERK-01 changes** from "requires an active session" to "requires the CURRENT
recovery words (ownership proof), rate-limited exactly like R-AC-05a/b/c".

## Checks

- `.venv/bin/python -m pytest src/tools/demiurgos-suite/wiki/tests/test_api_auth.py src/tools/demiurgos-suite/wiki/tests/test_account.py -q`
- `cd frontend && npm run typecheck`
- `cd frontend && npm test -- --run`

## Progress

- [ ] Backend guard
- [ ] Frontend gating
- [ ] Tests rewritten + regression added
- [ ] Parent verification
- [ ] Independent verification
