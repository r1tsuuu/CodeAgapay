# CodeAgapay audit

Snapshot of `main` at `5d52ee2` (15 Nov 2026), taken before the handover work on `feature/handover-finalization`. It records what is there, what is risky, and how the handover brief maps onto this codebase.

## 1. Stack

| Layer | What's used | Notes |
| --- | --- | --- |
| Language | Python 3.13 (`.python-version`) | |
| Framework | Django 5.2.18, server-rendered templates | One deployable app: a modular monolith already |
| Auth | django-allauth 65.19.7, Google only | `SOCIALACCOUNT_ONLY`, no passwords for learners |
| DB | SQLite locally, Neon Postgres in production (`DATABASE_URL`) | `conn_health_checks=True` for Neon's idle closes |
| Static | WhiteNoise, hashed and compressed when `DEBUG=False` | |
| Server | Gunicorn, 60 s timeout (`gunicorn.conf.py`) | Long because AI lessons are written inside a request |
| AI | Groq (main) and Cloudflare Workers AI (backup), both through the `openai` package | Optional: the app runs with no keys |
| Frontend | Vanilla JS (8 files, 56 KB), one stylesheet (`static/css/main.css`, 5,760 lines, 108 KB), SVG mascots | No build step, no framework |
| Browser runtimes | CodeMirror 5 and sql.js from cdnjs, Pyodide from jsDelivr | Loaded only when a learner opens the code panel |
| Email | Gmail SMTP from a laptop (`send_reminders`) | Render free blocks SMTP |
| Hosting | Render free web service, Singapore | Sleeps after 15 min idle (out of scope for this brief) |

No new framework is needed. Nothing in the brief needs a JS framework, a build step, or an animation library: the landing work fits the existing CSS and small vanilla JS files.

## 2. Folder structure

| Folder | Holds |
| --- | --- |
| `config/` | Settings, root URLs, WSGI, a test runner that forces safe AI defaults |
| `accounts/` | `LearnerProfile`, landing page, welcome, profile and settings, unsubscribe |
| `content/` | Curriculum models, admin, link checker, AI drafting commands, `drafts/*.json`, review queue |
| `diagnose/` | Guided onboarding (`onboarding.py`), the old form flow, skill check scoring (`scoring.py`) |
| `learning/` | Curated plans (`planner.py`, `journey.py`, `grading.py`), AI plans (`outline.py`, `lessons.py`, `ai_plan.py`, `ai_views.py`), practice, code panel, rewards, reminders, prompts |
| `assistant/` | AI providers, `/help/ask/`, daily caps (`service.py`) |
| `templates/`, `static/` | Pages, one stylesheet, vanilla JS, mascots and avatars |
| `fixtures/content.json` | The Python track (8 topics) |
| `docs/plan-framework.md` | The team's AI plan framework v2.1 (accepted 9 Nov 2026) |
| `notifications/` | Empty: only `migrations/__pycache__`, not in `INSTALLED_APPS` |

## 3. Data model

Curriculum (admin-edited): `Path` (goal) → `PathTrack` → `Track` → `Topic` (with self-referencing `prerequisites`) → `Resource`, `Tip`, `SkillQuestion`, `QuizItem`, `PracticeTask`. `Track` also has `SetupStep` and `ProjectIdea`.

Learner data: `LearnerProfile` (experience, hours, path, target weeks, device, hint style, reminders), `SkillCheckAttempt`/`SkillAnswer`, `TopicMastery` (status plus evidence; unique per learner and topic), `LearningPlan` (one active per learner and track, enforced by a conditional `UniqueConstraint`), `PlanItem`, `PlanProject`, `QuizAttempt`, `PracticeSubmission`, `PlanFeedback`, `AIUsage` (counts only, never text).

AI plan data (behind `AI_PLANS`): `PlanOutline` (AI-written modules and lessons as JSON), `GeneratedLesson` (versioned AI-written lessons), `LessonProgress`.

Progress is computed from `PlanItem.status` and never stored. There is no curriculum version on plans: a plan points at live `Topic` rows, so editing or deleting a topic changes or removes it from every existing plan (`on_delete=CASCADE` on `PlanItem.topic`).

## 4. Routes

Every page needs login (`LoginRequiredMiddleware`) except `home` (shows the landing page to visitors), allauth, admin login and `unsubscribe/<uuid>/`.

| Area | Routes |
| --- | --- |
| Accounts | `/`, `/welcome/`, `/profile/` (+ `icon/`, `details/`, `setup/`, `delete/`), `/settings/` (+ `reminders/`), `/unsubscribe/<uuid>/` |
| Onboarding | `/start/`, `/start/check/` (guided); `/about/`, `/skill-check/`, `/skill-check/questions/`, `/result/` (form fallback) |
| Curated plan | `/plan/`, `/plan/build/`, `/plan/finished/`, `/plan/items/<id>/status/`, `/plan/items/<id>/move-on/`, `/plan/pace/`, `/plan/report/` |
| AI plan | `/plan/retry/`, `/plan/lessons/<key>/` (+ `check/`, `rewrite/`, `move-on/`, `status/`, `rate/`, `set-up/`, `update-lessons/`) |
| Topics | `/learn/<track>/setup/`, `/learn/<topic>/` (+ `practice/`, `quiz/`, `quiz/result/`) |
| AI helper | `POST /help/ask/` (JSON, always 200), `/help/test/` (staff only) |
| Admin | `/admin/`, `/admin/review/` (staff only) |

There is no `/health` endpoint.

## 5. Auth and authorization

- Google sign-in only for learners; admin uses Django's password login.
- Learner objects are fetched through the signed-in user: `PlanItem` lookups filter on `plan__learner__user=request.user`; AI lessons resolve only from the learner's own active outline; `/help/ask/` takes a topic slug (public curriculum) and checks a quiz item belongs to that topic. I found no cross-user read or write path, but there are no tests that try one; they should be added.
- `delete_account` cascades every learner row.
- `unsubscribe` is CSRF-exempt and login-free on purpose; the stored UUID is the proof. GET only asks, POST changes.

## 6. AI integration

- `assistant/service.py`: providers in order (Groq hint model, Groq plan model for planning, Cloudflare), one retry on a short rate limit, request time budget, JSON parsing, daily caps.
- Caps are on the server, in `AIUsage` with `select_for_update`: hints and practice feedback (`AI_DAILY_LIMIT`, 20), plan intakes (`AI_INTAKE_DAILY_LIMIT`, 2), AI lessons (`AI_LESSON_DAILY_LIMIT`, 12). A failed call gives the message back.
- Fallback: with no keys, the cap reached or both providers down, the help endpoint returns the topic's curated tips and links (and the quiz hint on quiz screens). The app works fully with the AI off.
- Context sent for hints: topic title, track, summary, tips, resource titles, hint level, hint style, the learner's question, and on quiz screens the quiz prompt and their answer. Never accepted answers, names, emails or account history.
- **AI-written plans are live.** `AI_PLANS=True` is set on Render (11 Nov 2026). With it on, the AI writes each learner's outline (its own module and lesson titles, not curated `Topic` rows) and writes each lesson the first time it opens. Links in AI lessons are kept only if their domain is on an allow list (`learning/lessons.py`), so the AI picks URLs within trusted sites. This is the team-accepted design in `docs/plan-framework.md`.

### Where prompts live

| Prompt | File |
| --- | --- |
| Hints (3 levels), practice feedback | `assistant/service.py` (inline) |
| Reading a typed onboarding answer | `diagnose/onboarding.py` |
| Tailoring a curated plan (topic picks, reasons, project) | `learning/tailoring.py` |
| AI plan outline, AI lesson, AI setup page | `learning/prompts/outline.md`, `lesson.md`, `lesson_setup.md` |
| Drafting topics, intros, practice for curators | `content/drafting.py` |

## 7. Where curriculum lives

Curriculum is spread over five places:

1. The database, edited in admin (source of truth in production).
2. `fixtures/content.json`: the Python track, loaded by hand on an empty database.
3. `content/drafts/*.json`: HTML, CSS, JavaScript, Java, SQL (5 topics each), Python practice and extra quiz items. Loaded by `load_drafts`, and by data migrations `0011_unlock_tracks` and `0012_practice_tasks`, which run on every deploy.
4. Data migration `0004_seed_paths`: the five paths.
5. `learning/setup_guides.py`: built-in VS Code, CodePen and Colab setup guides, in Python code.

There is no schema check for the draft JSON beyond what `load_drafts` and the model `clean()` methods do, and no curriculum version.

## 8. Environment variables

All read in `config/settings.py` with defaults. `.env.example` exists and is current, except that `SITE_URL` is used but not listed. `.env` is gitignored. Secrets are never logged by the code I read.

**Risk:** the local `.env` on the lead developer's machine points `DATABASE_URL` at production Neon (needed for the weekly jobs). Any `manage.py` command run without an override, including `migrate` and `test`, targets production. The README warns about tests; nothing stops it.

## 9. Tests

- 493 tests in 21 files, about 9 s on SQLite. All AI calls are mocked; the test runner forces AI off whatever `.env` says.
- **Bug:** the suite only passes with `DEBUG=True`. With `DEBUG=False` (the value in the current local `.env`), `SECURE_SSL_REDIRECT` turns every request into a 301 and 220 tests fail. The test runner should switch the redirect off.
- No lint, formatter or type checker is configured (no ruff, flake8, mypy). No CI: GitHub Actions was removed on purpose; tests run by hand.
- Missing coverage the brief asks for: cross-user access, curriculum validation, `/health`.

## 10. Dependencies

All 10 pinned packages are used: Django, allauth, django-environ, dj-database-url, psycopg, whitenoise, gunicorn, openai (AI), Pygments (`lesson_format.py`, code colouring), requests (link checker). None to remove.

## 11. Dead or leftover code

| Item | State |
| --- | --- |
| `notifications/` | Empty folder (only a stale `__pycache__`). Safe to delete |
| `assistant/test_page`, `templates/assistant/test_page.html`, `static/js/help_test.js` | A staff-only page from before the help panel existed. Superseded; can go |
| `AI Learning Plan Framework.pdf` (580 KB), `CodeAgapay AI Learning Plan Framework v2.pdf` (160 KB) | Snapshots of `docs/plan-framework.md` in the repo root; the v1 PDF is superseded |
| The `/about/` form and full skill check | Still linked as "Prefer a short form instead?" and used as a fallback. Not dead |
| Roboto font | Loaded on every page for one rule (`main.css` line 899) |

## 12. Security

| Finding | Severity | Notes |
| --- | --- | --- |
| Local `.env` points at production DB | High (operational) | See section 8 |
| No HSTS | Low | `check --deploy` warns (W004). Safe to add a short `SECURE_HSTS_SECONDS` |
| Third-party scripts without Subresource Integrity | Medium | CodeMirror, sql.js (cdnjs) and Pyodide (jsDelivr) run on learner pages; a pinned version plus `integrity` hashes would stop a tampered CDN file |
| No Content Security Policy | Low | Inline scripts would need auditing first |
| No burst rate limit on `/help/ask/` | Low | The daily cap is enforced on the server and atomically. A short burst can still use 20 messages in a second, but that's the learner's own quota |
| Input validation | OK | Help questions and answers are cut to 500 characters, practice answers to 4,000, report text to 500; statuses checked against an allow list; hours clamped 1 to 40 |
| No structured logging config | Low | Django defaults only; provider failures logged with `exc_info`. No secrets or learner text are logged by the code |
| Prompt injection | Low | Learner text goes to the model inside fixed rules; no tool use, and the reply is shown as plain text |

## 13. Accessibility and mobile

Good already: skip link, `aria-live` on hint logs, labelled controls in the help panel, `:focus-visible` styles, `prefers-reduced-motion` in CSS and in `mascots.js`, a phone layout with a bottom menu bar.

Contrast problems (WCAG AA needs 4.5:1 for normal text):

| Pair | Ratio | Where |
| --- | --- | --- |
| White on `--lagoon` `#3CC6B6` | 2.11 | `.button-lagoon` (landing "Show the next hint") |
| `--teal` `#0E7C7E` on `--cream` | 4.41 | Body links on the cream background |
| `--error` `#E23B3B` on `--cream` | 3.77 | If used for error text |
| `--success` `#2FA866` on `--paper` | 2.88 | If used for text |

`--ink-soft` on cream (4.91), white on berry (5.02) and white on teal (5.0) pass. I haven't measured Lighthouse yet; that comes with Phase 4.

## 14. Conflicts between the brief and the repo

These need a decision before Phases 1 to 3:

1. **Deterministic plans vs live AI-written plans.** The brief says plans must be deterministic and the AI must not invent prerequisites or resources. Production runs `AI_PLANS=True`: the AI writes the outline (its own lessons, not curated topics) and the lessons, and chooses links within allowed domains. The team accepted this design in `docs/plan-framework.md` v2.1. Meeting the brief means turning `AI_PLANS` off, or reducing AI plans to explaining a deterministic plan.
2. **Curriculum as versioned files vs admin editing.** The repo's model is "curators edit everything in admin, no coding". Moving curriculum to versioned files changes who can edit it and how (pull requests instead of admin).
3. **CI.** The brief asks for schema validation and a dead-link check in CI. GitHub Actions was removed deliberately; the team runs tests by hand and keeps the production DB URL out of GitHub.
4. **Language of lessons.** The brief asks for an English and Filipino interface and a choice of English, Filipino or Taglish explanations. A recent commit (`fc1769b`) chose "lessons, plans and feedback in English; Taglish only in Need help".
5. **The taste skill vs "keep the design identity".** `design-taste-frontend` is a full website kit: it deals new palettes and type pairings, ships its own 100 KB CSS system, wants stock photographs, and forbids scroll reveals. The brief says keep the colours, type, mascots and voice. **Decided:** this is a refinement, so only its rules for copy, focus, tap targets, contrast, equal edges and motion restraint are applied, by hand. Its palettes, kit CSS, photographs and gate hook are not used.

## 15. The brief adapted to this stack

| Brief item | Plan here |
| --- | --- |
| Modular monolith, layers separated | Already true. Keep the apps; no restructuring |
| Versioned, validated curriculum | Depends on conflict 2 |
| Deterministic plans | `learning/planner.py` already is; depends on conflict 1 for AI plans |
| Server validation, server-side AI cap | Mostly done; add tests |
| `/health`, structured logging, `.env.example` | Add `/health/` (DB ping, no secrets), a `LOGGING` config, `SITE_URL` in `.env.example` |
| Dead code | Remove `notifications/`, the help test page, the v1 PDF |
| Tests | Add authorization, AI cap, AI context, curriculum validation and health tests; fix the `DEBUG=False` failures |
| Onboarding | Exists: goal, project, experience, hours (1–2, 3–5, 6–10, 10+), optional deadline, device, hint style. Add "desired outcome" and "recommend a language" only if still wanted after conflict 1 |
| Plan preview before sign-in | New: a static, deterministic preview on the landing page from curated data |
| Weekly units, flexibility | Mostly exists (done, skip, undo, move on, pace, change answers). Gaps: defer, pause |
| New tracks and languages | Curation work. Drafts exist for 5 tracks; TypeScript, C# and C++ have none. Ship only with a reviewed path |
| Agapay focused actions | `help.js` is a free-text chat with stepped hint levels; add action buttons that set the request type on the server |
| Landing page | Exists (hero, how it works, hint demo, paths, close). Add the goal selector preview, sample week, trust section; fix contrast |
| Handover docs | New: `ARCHITECTURE`, `CURRICULUM`, `AI`, `RUNBOOK`, `HANDOVER`; refresh README |
| Lint, typecheck, build | None configured. Proposed: `python manage.py check`, `makemigrations --check`, `collectstatic --dry-run`, and the tests, as one script. Adding ruff is optional |
