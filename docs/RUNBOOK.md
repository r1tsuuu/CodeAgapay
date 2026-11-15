# Runbook

What to do when something breaks on the live site. Render free has no shell, so every command below runs from a laptop with the repo, its virtualenv, and `DATABASE_URL` set to the Neon connection string for that one command:

```bash
DATABASE_URL="<neon url>" python manage.py <command>
```

Never leave the production URL in a shared `.env`, and never paste it into chat, issues or logs.

## First checks

1. Open `https://codeagapay.onrender.com/health/`. `{"status": "ok", "database": "ok"}` means Django and the database are up. A 503 means the database is unreachable. No answer for 30 to 60 seconds usually means Render is waking the service from sleep.
2. Render dashboard → the `codeagapay` service → **Logs**. Logs are JSON lines; search for `"level": "ERROR"` or a logger name such as `assistant.service`.
3. Render → **Events**: did a deploy just fail or finish?

## Login failures

| Symptom | Cause | Fix |
| --- | --- | --- |
| Google says `redirect_uri_mismatch` | The site's address isn't an authorised redirect URI | Google Cloud console → Credentials → the OAuth client → add `https://<host>/accounts/google/login/callback/` |
| Only some people can log in | The OAuth consent screen is in Testing | Publish it to production |
| Server error after Google, `MultipleObjectsReturned` in logs | A Google "Social application" was added in admin as well as in settings | Delete the one in admin (Social accounts → Social applications) |
| Callback fails over http | `SECURE_PROXY_SSL_HEADER` missing or `DEBUG=True` in production | Keep `DEBUG=False` on Render |
| `CSRF verification failed` on a custom domain | Domain not trusted | Add it to `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS` on Render |

## AI provider outage

Learners keep working: hints fall back to curated prompts, tips and links, and messages aren't counted when the AI fails. Logs show `AI provider groq ... failed`.

1. Check https://groqstatus.com. A 429 in the logs means the free quota is used up for now; it resets on its own.
2. If Groq is down for long, make sure Cloudflare Workers AI is configured (`CF_ACCOUNT_ID`, `CF_API_TOKEN`) so it takes over.
3. With `AI_PLANS=True`, new learners whose plan can't be written see a "try again" page or the curated plan. To give everyone curated plans during a long outage, set `AI_PLANS=False` on Render (existing AI plans keep working once the AI is back).
4. A leaked or revoked key: create a new one in the Groq console, update `GROQ_API_KEY` on Render, revoke the old one.

## Database issues

| Symptom | Fix |
| --- | --- |
| `/health/` returns 503, logs show connection errors | Neon dashboard: is the project suspended or over its free compute? The free tier pauses idle databases and wakes them on the next connection; a few failed requests while waking are normal |
| `password authentication failed` | The Neon password was reset. Copy the new connection string into Render's `DATABASE_URL` |
| A migration failed during deploy | The build stops before the new code goes live. Read the error in Render's deploy log, fix it on a branch, test with `./scripts/check.sh` and a copy of production (Neon branch), redeploy |

## Broken resource links

```bash
python manage.py validate_curriculum --links              # the files, no database needed
DATABASE_URL="<neon url>" python manage.py check_links    # production, results in admin
```

Fix the URL in `content/curriculum/tracks/<track>.json`, or set the resource's `"is_active": false`, then import (see [CURRICULUM.md](CURRICULUM.md)). For an urgent fix, edit the resource in admin, then run `export_curriculum` so the files keep the change.

## Rollback

- **Code:** Render → the service → **Deploys** → pick the last good deploy → **Rollback**. Then revert the bad commit on `main` with `git revert`, so the next deploy doesn't bring it back.
- **Migrations:** Render's rollback doesn't undo migrations. All handover migrations only add tables and columns, so older code runs fine on the newer schema. If a migration must be undone: `DATABASE_URL="<neon url>" python manage.py migrate <app> <previous migration>`, after a backup.
- **Curriculum:** check out the previous version of `content/curriculum/` and run `import_curriculum`. Plans keep their topics either way.

## Backups

- **Before any schema change or risky command:** create a Neon branch of production (Neon console → Branches → Create branch). It's an instant copy you can restore from or test migrations on.
- **Point-in-time restore:** Neon keeps a short history of changes on the free tier (check the current window in the Neon console). Restore from the console.
- **Plain dump** (needs `pg_dump` installed): `pg_dump "<neon url>" --format=custom --file=codeagapay-$(date +%F).dump`. Store it somewhere private; it contains learner data.
- **Curriculum:** it's in Git. `export_curriculum` copies admin edits back into the files.

## Regular jobs

Run weekly from a laptop (Render free has no cron):

- `send_reminders` (see the README). It needs the `EMAIL_*` settings in the laptop's `.env`.
- `check_links` or `validate_curriculum --links`.
- Admin review: Help feedback (Not helpful, Reported), Plan feedback, Generated lessons flagged or rated down.
