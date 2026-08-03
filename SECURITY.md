# Security Policy

## Credential Boundary

Never commit API keys, GitHub tokens, Codex authentication files, cookies, private keys, or quota
service credentials. Keep them in the operating system credential store or process environment.
The repository ignores common local credential files as a secondary safeguard, but ignore rules are
not a substitute for reviewing `git diff --cached` before every push.

The Reader treats custom Responses API endpoints as third-party services. A custom endpoint may use
only an explicitly configured `READER_TRANSLATION_API_KEY`. General `OPENAI_API_KEY` and Codex
`auth.json` credentials may be used only with `https://api.openai.com`.

## Private Runtime Data

The following paths can contain private research material or user activity and must remain local:

- `tasks/`
- `reader/user-data/`
- `reader/docs/`
- `reader/site/`
- `reader/.venv/`

The personalized learning profile in `docs/learning-profile.md` is intentionally public. Review any
new profile fields before committing them.

## Reporting And Response

Do not include a real secret in a public issue. Use GitHub's private vulnerability reporting when it
is enabled, or contact the repository owner privately with a redacted reproduction.

If a credential is committed or pushed, revoke or rotate it immediately, remove it from Git history,
and verify that generated artifacts and forks do not retain the value. Merely deleting it in a later
commit is insufficient.
