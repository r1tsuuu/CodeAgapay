# Curriculum

Everything learners study is in versioned JSON files in `content/curriculum/`, kept in Git. Change a file, check it, open a pull request, and import it. No coding is needed to add a track.

```
content/curriculum/
  curriculum.json        the version and the paths (goals)
  tracks/<slug>.json     one track: setup steps, project ideas and topics
```

## The workflow

1. Make a branch and edit the files (any text editor; VS Code shows JSON errors as you type).
2. Bump `version` in `curriculum.json` when the change matters to learners. Use the date, e.g. `2026.11.20`; add `.1`, `.2` for a second change the same day.
3. Run the checks:
   ```bash
   python manage.py validate_curriculum          # rules only, no database, a second or two
   python manage.py validate_curriculum --links  # also opens every link
   ./scripts/check.sh                            # everything, before the pull request
   ```
4. See what an import would do, on your local database:
   ```bash
   python manage.py import_curriculum --dry-run
   ```
5. Open a pull request. After merging, the curriculum reaches production either automatically (`CURRICULUM_AUTO_IMPORT=1` on Render, see below) or with `DATABASE_URL="<neon url>" python manage.py import_curriculum` from a laptop.

### Quick fixes in admin

Admin still edits the same tables. If you fix something there, copy it back so the next import doesn't undo it:

```bash
DATABASE_URL="<neon url>" python manage.py export_curriculum
git diff content/curriculum/      # review, then commit on a branch
```

### Switching production over (one time)

The files were generated from the repo's own content on 15 Nov 2026. Production may have admin edits that aren't in them. Before the first import on production:

1. `DATABASE_URL="<neon url>" python manage.py export_curriculum`, then review and commit the diff.
2. `DATABASE_URL="<neon url>" python manage.py import_curriculum --dry-run` should then say little or nothing.
3. Set `CURRICULUM_AUTO_IMPORT=1` on Render so each deploy imports the files (`build.sh`).

## What the import does

`import_curriculum` makes the database match the files, and is safe to run on production and to run twice.

| Thing | Matched by | When it's in the database but not the files |
| --- | --- | --- |
| Path, track, topic | `slug` | Paths and tracks are left alone. Topics are kept and listed ("kept so plans that have it still work") |
| Resource | position in the topic's list | Hidden (`is_active` off), never deleted. A changed URL resets its link-check result |
| Tip, setup step | position | Deleted |
| Project idea | position | Made inactive |
| Skill question, quiz item, practice task | position | Deleted only if no learner answered it; otherwise kept and listed |

Each import that changes anything is recorded as a **Curriculum release** (admin, read-only), and new plans store that version in `LearningPlan.curriculum_version`. A topic that is in anyone's plan can't be deleted (`PROTECT`), so old plans keep rendering after content changes. To retire a topic, take it out of the files: it stays for plans that have it and is never added to new ones.

Because children are matched by position, **reordering** quiz items or questions rewrites them in place; that's fine, but avoid reordering items learners have answered, or their old answers will sit next to a different question.

## The rules (`validate_curriculum`)

The rules live in `content/curriculum.py`: the `*_SHAPE` dicts give each field a type, and `validate` checks everything else. They run in `./scripts/check.sh` and before every import.

- Every field has a type; unknown field names are refused (they're usually typos).
- Slugs are lowercase words joined by hyphens. Topic slugs are unique across all tracks, because lesson URLs use only the topic slug: prefix them with the track (`js-loops`).
- Prerequisites name topics in the same track, never the topic itself, and never form a circle.
- `estimated_minutes` is between 5 and 600.
- Up to 3 key terms, each `{"term": ..., "definition": ...}`.
- Links are `https://`. Resource `kind` is `video`, `article`, `interactive` or `docs`.
- Skill questions have at least two choices, and `correct_index` (counting from 0) points at one. The page adds "I don't know yet" itself.
- Quiz prompts mark the blank with `___`; `accepted_answers` has at least one answer.
- **A live track (`"is_active": true`) must be complete**: every topic has an active resource and quiz items, and the track has a project idea with "done when" checks. This is the bar for calling a language supported.
- Paths name real tracks, each once.

## Field reference

`curriculum.json`

```json
{
  "version": "2026.11.15.1",
  "paths": [
    {
      "slug": "website",
      "title": "Make a website",
      "tagline": "A page for your org, a portfolio, an event site.",
      "language_reason": "Every web page starts as HTML, so ...",
      "is_active": true,
      "tracks": ["html", "css", "javascript"]
    }
  ]
}
```

`tracks/<slug>.json`: `slug`, `name`, `order`, `description`, `is_active`, `setup_check`, `setup_steps` (`title`, `body`, `link`), `project_ideas` (`title`, `brief`, `done_when`, `is_active`), and `topics`. Each topic:

| Field | Required | Notes |
| --- | --- | --- |
| `slug`, `title`, `summary` | yes | `summary` is what the learner can do after it, one sentence |
| `estimated_minutes` | yes | Drives the weekly split |
| `prerequisites` | | Topic slugs in this track |
| `resources` | yes | `title`, `url`, `kind`, `estimated_minutes` (default 15), `is_active` |
| `tips` | | Short strings. Also used by Agapay as grounding and fallback |
| `skill_questions` | | `prompt`, `code_snippet`, `choices`, `correct_index` |
| `quiz_items` | | `prompt` with `___`, `accepted_answers`, `hint`, `explanation`, `case_sensitive`. Pass mark is 70%: with 2 or 3 items every answer must be right, so write 4 or more if one mistake should still pass |
| `practice_tasks` | | `prompt`, `starter_code`, `sample_answer`, `checklist`, `approved` |
| `why_it_matters`, `key_terms`, `explanation`, `example`, `example_output`, `intro_approved` | | The "In a nutshell" intro; shown only when `intro_approved` is true |

## Adding a track or language

1. Copy a small track file (e.g. `tracks/sql.json`) to `tracks/<new-slug>.json`, set `"is_active": false`.
2. Write 5 to 9 topics, each with 2 resources from established free sources (official docs, MDN, freeCodeCamp, W3Schools, javascript.info and similar), 2 tips, 1 or 2 skill questions, 3 or 4 quiz items, and a practice task if you can.
3. Add a project idea with "done when" checks, and setup steps.
4. Add it to a path in `curriculum.json` (or a new path, also `"is_active": false`).
5. Have someone else review every topic and run each example. Then set `is_active` to `true` on the track and path; the validator then insists the track is complete.

A language isn't "supported" until it has all of that and a review. Ship fewer languages done well rather than many shallow ones. TypeScript, C# and C++ are not started (see [HANDOVER.md](HANDOVER.md)).

## Dead links

- `python manage.py validate_curriculum --links` (or `./scripts/check.sh --links`) opens every active link in the files and fails on a 404 or 410. Sites that refuse scripts show as "check by hand".
- `DATABASE_URL="<neon url>" python manage.py check_links` checks the links in the production database and records the result for admin (Resources, filter by link status).

Run one of them weekly. Links are never hidden automatically: fix the URL in the files, or set the resource's `is_active` to `false`.
