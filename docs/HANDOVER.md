# Handover

For the team taking over CodeAgapay. Start with the [README](../README.md), then [ARCHITECTURE.md](ARCHITECTURE.md). This page lists what has to change hands, what doesn't work yet, and what to do next.

## Accounts and credentials to transfer

No secret is written here. Hand each one over in person or through a password manager, then rotate it.

| What | Used for | Where the secret lives | On handover |
| --- | --- | --- | --- |
| GitHub repository | Code, pull requests; `main` deploys to Render | GitHub | Transfer the repo (or add the new owners as admins) |
| Render web service `codeagapay` (free, Singapore) | Hosting at https://codeagapay.onrender.com | Render environment variables | Transfer the service or recreate it under the new team's account and reconnect the repo |
| Neon project (free, Singapore) | Production Postgres | `DATABASE_URL` on Render | Transfer the project, then **reset the database password** and update Render |
| Google Cloud OAuth client | Google sign-in | `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` on Render | Add the new owners to the Google Cloud project; rotate the client secret |
| Groq account | Main AI provider (free tier, no billing) | `GROQ_API_KEY` on Render | New account or transfer; create a new key, revoke the old one |
| Cloudflare account (optional) | Backup AI provider (free tier) | `CF_ACCOUNT_ID`, `CF_API_TOKEN` | Only if configured; rotate the token |
| Gmail `codeagapay.reminders@gmail.com` | Sends reminder emails | App password in the `.env` of the machine that sends | Change the account password and create a new app password |
| Weekly reminder job | `send_reminders`, Mondays | Currently a scheduled job on a team member's laptop | Move it to a machine the new team controls (any computer with the repo, the `.env` and a weekly scheduler) |
| Django admin accounts | Curation and review | The database | Create accounts for the new curators; remove or reset the old ones |
| Figma file | Design source for colours and type | Figma | Share edit access |
| Domain | None: the site uses the `onrender.com` address | | If you add one: Render custom domain, `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`, Google OAuth redirect URI |
| AI billing | None: free tiers only. The project's hard rule is zero cost | | Keep it that way, or budget before switching to paid tiers |

## Before the first deploy of this branch

1. Back up: create a Neon branch of production.
2. Merge and deploy. Migrations only add tables and columns; existing learner data is kept.
3. Switch the curriculum over once (see [CURRICULUM.md](CURRICULUM.md#switching-production-over-one-time)): `export_curriculum` from production, commit the diff, then set `CURRICULUM_AUTO_IMPORT=1` on Render.
4. Open `/health/` and log in once to check.

## Known limitations

- **AI-written plans aren't deterministic.** Production runs `AI_PLANS=True`: the AI writes each learner's outline and lessons, inside rules the code checks ([plan-framework.md](plan-framework.md)). The curated planner, used when `AI_PLANS` is off or the AI fails, is fully deterministic. This was a deliberate team decision; see the trade-off under next steps.
- **Filipino and Taglish replies aren't reviewed translations.** Agapay can explain in Filipino or Taglish, but the model writes them. The interface, lessons and plans are English only.
- **Programming Foundations isn't live.** It's in the files with `is_active: false`, waiting for a review.
- **Render free sleeps** after 15 idle minutes; the first visit then takes 30 to 60 seconds.
- **No cron.** Reminders and link checks run by hand or from a laptop.
- **Third-party scripts without integrity hashes.** GSAP on the landing page is pinned with integrity hashes, but the coding panel loads CodeMirror and sql.js from cdnjs and Pyodide from jsDelivr, pinned to versions but without Subresource Integrity.
- **No HSTS or Content Security Policy** yet (`check --deploy` warns about HSTS).
- **No burst rate limit** on `/help/ask/`; the daily cap is enforced, so the worst case is a learner using their own 20 messages quickly.
- From the README's known issues: 70% pass mark means 2- or 3-item quizzes need every answer right; the quick check covers only a path's first track; reviews use a fixed 7-day rule; onboarding answers live in the session until confirmed; opening a lesson isn't recorded as activity for reminders.
- **Lighthouse** (landing page, mobile, throttled, local server): Performance 83 to 89 (86 after the GSAP hero; varies run to run), Accessibility 100, Best Practices 100, SEO 100. The main cost is the Google Fonts stylesheet and the 110 KB stylesheet, both render-blocking.

## Not done from the handover brief, and why

| Item | Why |
| --- | --- |
| TypeScript, C# and C++ | A language counts as supported only with a reviewed beginner path, prerequisites, free resources, exercises, checkpoint questions and project rubrics. None has been written or reviewed yet. Follow "Adding a track" in [CURRICULUM.md](CURRICULUM.md) |
| Mobile/interactive projects track | No reviewed beginner path built on what the current tracks teach; it would need the JavaScript track first and a choice of free tools |
| Interface in Filipino | Decided against for now: shipping machine-translated text without review would break the brief's own rule. Django's i18n is on (`USE_I18N`), so strings can be wrapped and translated later |
| CI in GitHub Actions | Decided against: the team keeps the production database URL out of GitHub and runs `./scripts/check.sh` by hand |
| Deterministic AI plans | Decided to keep `AI_PLANS` live (see above) |
| Type checking | The code has no type hints to check; `ruff` and Django's checks run instead |

## Next steps, in priority order

1. **Switch production to the curriculum files** (one time, above). Until then, admin edits and the files can drift.
2. **Move the reminder job** off a personal laptop and **rotate every secret** in the table above.
3. **Review and launch Programming Foundations**: check each topic, then set `is_active` on the track and the "Start from zero" path.
4. **Decide the future of AI plans.** Either keep them, sampling AI lessons weekly in admin as the framework says, or set `AI_PLANS=False` so every plan comes from curated topics and the AI only hints. Curated plans are cheaper, predictable and testable; AI plans cover paths without curated topics.
5. **Harden the edges:** add Subresource Integrity hashes for the CDN scripts (or self-host them), set a short `SECURE_HSTS_SECONDS`, and consider a per-minute limit on `/help/ask/`.
6. **Review Agapay feedback weekly** (admin → Help feedback) and improve the tips of topics with many "Not helpful" ratings.
7. **Add a language properly** (TypeScript is the natural next one after JavaScript), following [CURRICULUM.md](CURRICULUM.md).
8. **Speed:** self-host the two fonts with `font-display: swap` and split the stylesheet per page to lift Lighthouse Performance.
9. **Filipino interface** with reviewed translations, if learners ask for it.
10. **Spaced review** instead of the fixed 7-day rule.
