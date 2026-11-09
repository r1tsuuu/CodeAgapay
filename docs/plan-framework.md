# CodeAgapay AI Learning Plan Framework

Version 2.1, accepted by the team on 9 November 2026. Outline step built in shadow mode (prompt `outline-2`).

This is the source of truth for how CodeAgapay's AI builds learning plans and lessons. The AI prompts and the code follow it. When a rule changes here, change the prompt or code that carries it out (see **Where** in each table) in the same pull request.

It replaces the general-purpose "AI Learning Plan Framework and Resource Dictionary" (version 1), which described plans for any topic. `CodeAgapay AI Learning Plan Framework v2.pdf` is a printable snapshot of this file and may lag behind it.

## 0. How to read this

Each rule has a status and says who enforces it.

| Status | Meaning |
| --- | --- |
| **Built** | In the app today. Reused by the new plan. |
| **v1** | Part of the first AI-generated plan implementation. |
| **Later** | Agreed direction, not in v1. |

| Enforced by | Meaning |
| --- | --- |
| **Prompt** | The AI is told to follow it. Nothing checks it automatically, so the weekly review (section 11) samples it. |
| **Code** | The app checks or carries out the rule itself, even when the AI ignores the prompt. |
| **Team** | People do it: curators, reviewers, whoever runs the regular jobs. |

If a rule matters for safety, grading or progress, it is enforced in **Code**. Prompts guide the content; code guards the result.

Where prompt text lives: v1 adds `learning/prompts/outline.md` and `learning/prompts/lesson.md`. They are short, written for the model, and name the sections of this file they follow. Don't paste this file into a prompt.

## 1. Purpose and scope

- **What the AI does:** writes each learner's plan outline (modules, lessons, project) at sign-up, and writes each lesson (explanation, example, practice, quiz) the first time the learner opens it.
- **What grounds it:** this framework, the learner's answers and skill check results, the allowed resource list (section 9), and any curated links the app already has for the subject.
- **Scope:** CodeAgapay's paths (Make a website, Automate boring tasks, Work with data, Make games and fun projects, Get ahead in CS class) and tracks (Python, JavaScript, HTML, CSS, Java, SQL). Not any topic. The language-learning, soft-skill and creative-skill parts of version 1 are removed.
- **Limit of v1:** lesson explanations come from the model's own knowledge, guided by these rules. The AI does not read the linked pages and teach from them yet; that is Retrieval in section 13.

## 2. How a plan is generated

Two small AI steps instead of one large one. They fit the free AI tiers, are faster, and let each lesson adapt to how the learner is doing.

| Step | When | What happens | Status | Where |
| --- | --- | --- | --- | --- |
| 1. Onboarding | Sign-up | Path, project, experience, topics used, hours per week, optional date, what helps when stuck; then the skill check | Built | `diagnose/onboarding.py`, `diagnose/views.py` |
| 2. Outline | After the learner confirms | One AI call writes the outline (section 5). Code checks and saves it. Code assigns weeks from hours per week | Built in shadow mode: saved for review in admin when `AI_OUTLINES` is on; learners don't see it until step 3 ships | `learning/outline.py`, `learning/prompts/outline.md` |
| 3. Lesson | First open of a lesson | One AI call writes it (section 6) using the learner's latest quiz results. Code checks and saves it; later visits show the saved lesson | v1 | new lesson generation module |
| 4. Check | End of each lesson | Code grades the mini-check and applies the score bands (section 7) | v1 | `learning/grading.py` |
| 5. Adapt | After a low score | The lesson is regenerated with a different explanation and example; retakes use new questions | v1 | lesson generation |
| Fallback | AI off, over its limit, or two bad replies | Today's curated plan: curated topics, rule-based order and weeks, template project | Built | `learning/tailoring.py` `build_plan_with_template` |

**Fallback gap:** only Python has curated topics today (HTML and CSS are drafted in `content/drafts/`). On other tracks the fallback can only show setup steps and ask the learner to try again later. The team still has to decide what learners see (section 14).

## 3. Learner inputs

| Version 1 input | In CodeAgapay | Status | Notes |
| --- | --- | --- | --- |
| Topic | Skill path, plus the learner's own project idea | Built | The path decides the tracks |
| Goal | Goal text and project idea | Built | Decides what is core and what is optional |
| Level | Experience answer plus skill check results per topic | Built | Mapped to beginner, intermediate or advanced for the depth table |
| Time per session | Not asked | v1 | Default 30 minutes, stated as an assumption |
| Total time or deadline | Hours per week, optional target date | Built | The app flags a plan that misses the date |
| Prior knowledge | Skill check statuses: shown, partly there, to work on, not checked | Built | Shown topics are skipped or become recaps |
| Preferred format | "What helps when stuck" (`LearnerProfile.hint_style`) | Built | Used for hints today; v1 also passes it to lesson generation |

Missing inputs: assume a complete beginner with 30-minute sessions and list every assumption at the top of the plan so the learner can correct it. *Prompt. v1.*

## 4. Core principles

| Principle | Status | Enforced by | How |
| --- | --- | --- | --- |
| **Beginner first.** Assume nothing unless the check showed it | Built | Code + Prompt | Skill check evidence decides what is known |
| **Build in layers.** A lesson uses only ideas taught earlier | v1 | Prompt + Code | Each lesson lists the lessons it needs; code rejects one that needs a later lesson |
| **One new idea at a time** | v1 | Prompt | Depth table, section 6 |
| **Learn by doing.** Every lesson has a try-it task | v1 | Code | A lesson without one fails validation |
| **Check often, low stakes** | v1 | Code | Mini-check after every lesson |
| **Tie everything to the goal** | v1 | Prompt + Code | Lessons are tagged core or optional; optional ones are cut first |
| **Show the finish line** | v1 | Code | Every lesson needs a "You will be able to" line |
| **Never invent resources** | v1 | Code | Links off the allowed list are removed (section 9). Today the AI never writes links at all (Built) |
| **Recover, do not repeat** | v1 | Code + Prompt | After a low score the lesson is regenerated differently |
| **Spaced recall** | Built | Code | Warm-ups and 7-day reviews (section 8) |
| **Visible progress** | Built | Code | The plan page leads with one next step; finish screen. Module progress lines are v1 |
| **Hints, never answers** | Built | Prompt | Three levels of hints in the help panel (`assistant/service.py`) |

## 5. Plan outline (written at sign-up)

Every plan has these parts, in this order.

| Part | What it holds | Status |
| --- | --- | --- |
| Overview | Goal, assumed level, total lessons and hours, assumptions, any conflict (for example, a big goal and a close date) with a realistic version | v1 |
| Setup | The track's curated `SetupStep`s ending with `Track.setup_check`. Not written by the AI | Built |
| Foundations | Basic building blocks; recaps when the skill check showed them | v1 |
| Modules | 3 to 5 lessons each, simple to complex, each with a one-sentence goal, a milestone ("you can now...") and a stuck path | v1 |
| Lessons (titles only) | Title, "You will be able to", minutes, core or optional, lessons it needs | v1 |
| Project | One project tied to the goal, with weekly steps and "done when" checks, adapted from a curated `ProjectIdea` when one fits | Built |
| Next steps and glossary | What to learn next; every key term from the saved lessons, in order, on the finish screen | v1 |

### Sequencing

| Rule | Enforced by | Status |
| --- | --- | --- |
| Each lesson only needs what came before | Prompt + Code | v1 |
| A first small win within the first two lessons after setup | Prompt | v1 |
| No lesson much harder than the one before it | Prompt | v1 |
| Include only what the goal needs | Prompt | v1 |
| Weeks fill up to hours per week; a lesson that doesn't fit starts the next week | Code (`planner.assign_weeks`) | Built |
| A lesson limit from hours per week and the target date (default 20, at most 30) is given to the AI; extra lessons are cut, optional ones first | Code (`outline.lesson_limit`, `parse_outline`) | Built (outline) |
| Modules longer than 5 lessons are split | Code | Built (outline) |
| When time is short, cut optional lessons first; never cut setup, key terms, mini-checks or the project | Code | v1 |

## 6. Lessons (written when first opened)

Every lesson has the same parts. Code rejects a lesson missing a required part.

| Part | Rule | Status |
| --- | --- | --- |
| You will be able to | One sentence | v1 |
| Time | Within the depth table's range for the level | v1 |
| Warm-up | 1 to 2 ungraded questions on the previous lesson, preferring ones the learner missed; none in the first lesson | Built for curated topics (`journey.warm_up`); v1 for generated lessons |
| Key terms | Up to 3 for beginners (5 intermediate, 7 advanced), each with a plain definition | Built (`Topic.clean` allows 3) |
| Why it matters | The problem this solves, before the how | Built |
| Explanation | At the depth for the level; no internals or history for beginners | Built |
| Example | Worked code with its exact output. Two at beginner level: one simple, one real-world, ideally from the learner's path | v1 (curated topics have one) |
| Try it yourself | Copy an example, change it, then build something small; no files, internet or installs for beginners | Built (`PracticeTask`) |
| Resources | 1 primary and up to 2 optional, from section 9 only | v1 |
| Mini-check | 2 to 3 auto-graded questions (1 if sessions are under 20 minutes) | v1 |

"Built" here means curated topics already follow the rule and the drafting prompts in `content/drafting.py` enforce it. v1 moves the same rules into the lesson prompt.

### Depth table

| Setting | Beginner | Intermediate | Advanced |
| --- | --- | --- | --- |
| Main ideas per lesson | 1 | 1 to 2 | 2 to 3 |
| New key terms | Up to 3 | Up to 5 | Up to 7 |
| Depth | What it is, why it matters, how to use it | Adds trade-offs and common mistakes | Adds how it works inside and edge cases |
| Examples per idea | 2: one simple, one real-world | 2 real-world | 1 real-world, 1 edge case |
| Lesson length | 15 to 30 minutes | 25 to 45 minutes | 30 to 60 minutes |
| Practice | Guided with hints | Partly guided | Open-ended |

Change from today: curated topics run 45 to 120 minutes and the drafting prompt allows 30 to 120. Generated lessons follow the table, so one curated topic may become two or three lessons.

### Taglish and English

This is about the language the AI writes in (outline, lessons, hints, feedback), not teaching spoken languages.

| Rule | Enforced by | Status | Where |
| --- | --- | --- | --- |
| Match the learner: Taglish if they write in Taglish, otherwise plain English | Prompt + Code | Built | `assistant/service.py` hint prompt |
| Detect common Tagalog words and add an explicit "reply in Taglish" note, because models drift back to English | Code | Built | `assistant/service.py` `language_note` |
| Plans are written in Taglish when the learner used Taglish | Prompt | Built | `learning/tailoring.py` `SYSTEM_PROMPT` |
| Same rule for generated lessons, using the learner's onboarding and help messages | Prompt + Code | v1 | lesson prompt |
| Code, keywords, function names and error messages stay in English | Prompt | v1 | lesson prompt |
| Taglish the way Filipino students mix it, not formal Tagalog; 2 or 3 sample explanations in the prompt | Prompt | v1 | lesson prompt |
| Tests: a Taglish learner gets a Taglish lesson, an English learner gets English | Code | v1 | tests |

## 7. Checks, quizzes and score bands

### Question rules

| Rule | Enforced by | Status |
| --- | --- | --- |
| Only formats the app can grade: multiple choice (correct choice stored) and fill-in-the-blank (all accepted answers) | Code | v1 (fill-in-the-blank is Built) |
| "Explain" questions are ungraded self-checks with a sample answer | Code | v1 |
| About 50% recall, 30% apply, 20% explain | Prompt | v1 |
| Every question has its answer and a one-sentence explanation | Code | v1 |
| Only test what was taught; no trick questions for beginners | Prompt | v1 |

### Checkpoints

| Checkpoint | Where | Status |
| --- | --- | --- |
| Setup check | End of setup, instead of a quiz | Built |
| Mini-check | End of every lesson | v1 |
| Topic quiz | Curated fill-in-the-blank quiz per topic, used by fallback plans | Built |
| Module quiz | After every 3 lessons (beginner), 4 (intermediate), 5 (advanced); 5 to 8 questions, at least 2 from earlier modules | Later |
| Final check | Before the project; 10 to 15 questions across all modules | Later |
| Project | End of the plan, with "done when" checks | Built |

### Score bands

Code: `learning/grading.py` (`PASS_PERCENT`, `ALMOST_PERCENT`, `QuizResult.band`) and `learning/planner.py` (`move_on_shaky`).

| Score | What happens | Status |
| --- | --- | --- |
| Pass mark | 70%, compared as exact fractions so 69.5% never passes | Built |
| 100% | Continue | Built |
| 70% to 99% | Continue; missed ideas come back in the next warm-up | Built |
| 50% to 69% | Suggest another resource and retake. v1: the retake has new questions | Built (new questions v1) |
| Below 50% | Re-teach. v1: regenerate the lesson with a different explanation and example, and check no needed lesson was skipped | Built (regeneration v1) |
| Two misses | Mark shaky, continue the plan, bring it back as a review | Built |
| 85% before a lesson | Skip it but still show its key terms (today a curated topic is skipped by passing its quiz at 70%) | Later |

A failed check never blocks the learner for good; there is always a next step. *Code. Built.*

## 8. Adapting to the learner

| Signal | What changes | Status |
| --- | --- | --- |
| Skill check result | Shown topics are skipped; partly-there topics become recaps | Built |
| Experience and results | Pick the depth table column | v1 |
| Low score on a lesson | Regenerate it: new explanation, new example, a different resource type | v1 |
| Missed questions | Come back first in the next warm-up (`journey.warm_up`) and the retake | Built for curated topics; v1 for generated lessons |
| What helps when stuck | Shapes hints today; v1 also shapes lesson examples and resource types | Built |
| Pace change | Weeks recomputed, progress kept (`planner.repace_plan`) | Built |
| Passed topics | Come back for a short review after 7 days (`journey.REVIEW_AFTER_DAYS`) | Built |
| Missed sessions | Progress never resets; opt-in reminder emails (`learning/reminders.py`) | Built |
| Plans over 2 weeks | One catch-up session a week; a review lesson after every 2 modules | Later |

## 9. Resources and grounding

| Rule | Enforced by | Status |
| --- | --- | --- |
| Keep a link only if its site is on the allowed list; otherwise drop the URL and keep the name and a search phrase | Code | v1 |
| Give the AI the curated links the app already has for the subject, and prefer them | Prompt | v1 |
| Free resources only; paid ones are not on the list | Team | v1 |
| Match the learner's level; no advanced docs for beginners | Prompt | v1 |
| Setup uses official sources and stays curated | Team | Built |
| Resources support the lesson; they never replace its explanation | Prompt | v1 |
| Weekly link check marks broken curated links (`check_links`) | Team | Built; checking AI-chosen links is Later |

### Allowed list

Trimmed from version 1's resource dictionary to free coding resources. The team opens and checks each row before launch and records the date. Code keeps this list as allowed domains.

| Resource | Sites | Best for | Level | Checked |
| --- | --- | --- | --- | --- |
| MDN Web Docs | developer.mozilla.org | HTML, CSS, JavaScript | Beginner to advanced | |
| Python docs | docs.python.org | Python tutorial and reference | Beginner to advanced | |
| W3Schools | w3schools.com | Quick beginner examples | Beginner | |
| freeCodeCamp | freecodecamp.org, youtube.com/@freecodecamp | Long beginner courses | Beginner to intermediate | |
| The Odin Project | theodinproject.com | Web development path | Beginner to intermediate | |
| Harvard CS50 | cs50.harvard.edu | Intro to programming | Beginner | |
| Khan Academy | khanacademy.org | Intro computing, JS drawing | Beginner | |
| Kaggle Learn | kaggle.com/learn | Python, data analysis | Beginner to intermediate | |
| Real Python (free articles) | realpython.com | Python articles | Beginner to advanced | |
| Exercism | exercism.org | Practice exercises | Beginner to advanced | |
| Google Colab | colab.research.google.com | Python with no install (phones, school PCs) | Beginner | |
| CodePen | codepen.io | HTML, CSS, JS with no install | Beginner | |
| Official installers | python.org, nodejs.org, code.visualstudio.com, git-scm.com | Setup only | Beginner | |
| Stack Overflow | stackoverflow.com | Searching error messages | Beginner to advanced | |

Removed from version 1: paid or mostly paid (Brilliant, Udemy, Google certificates, Codecademy Pro, LeetCode premium) and non-coding (Duolingo, Forvo, Easy Languages, language exchange apps, Kahoot, Investopedia, Desmos, Wolfram Alpha, OpenStax, Project Gutenberg, Open Library). YouTube is allowed by channel plus a search phrase until specific videos are checked.

## 10. Checks on every AI reply

These run in code before anything is saved or shown. They are what make AI-written plans safe to show without approving each one first.

| Check | If it fails | Status |
| --- | --- | --- |
| Valid JSON in the expected shape (appendix A) | Try the next provider; for an outline with no usable lessons, ask once more, then fall back | Built (`ask_model_json`, `outline.generate_outline`) |
| Outline: lessons have titles; minutes within the depth table; known kinds | Repair in code (drop, clamp, default) and record the repair; no extra AI call | Built (`outline.parse_outline`) |
| Lesson: required parts present (section 6) | Retry once, then fall back | v1 |
| Lessons only need earlier lessons | Drop references to later or unknown lessons | Built (outline) |
| Every question is gradable | Drop it; retry if fewer than 2 remain | v1 |
| Every link is on the allowed list | Remove the URL, keep the name and search phrase | v1 |
| Text within length limits; no HTML or scripts | Trim or strip | Built for trimming |
| Daily limits per learner | Plans: build without AI (`AI_INTAKE_DAILY_LIMIT`). Lessons: show a try-later message (`AI_LESSON_DAILY_LIMIT`, v1) | Built for plans; v1 for lessons |

AI providers: Groq first (`GROQ_PLAN_MODEL`, then `GROQ_MODEL`), Cloudflare Workers AI as backup. *Code. Built.* Each saved outline records the model, prompt version and token counts (`PlanOutline`). *Code. Built.* Lessons will too. *v1.*

### Keeping calls small

Every AI call costs free-tier quota, so the code does everything it can by itself and asks the model only for what needs judgment. *Code. Built for the outline; the lesson step follows the same rules.*

| Method | Saves | Accuracy kept by |
| --- | --- | --- |
| The model writes only modules, lesson titles, minutes, kinds, needs and the project. Code adds lesson numbers and keys, weeks, totals, module progress, stuck paths and setup (and, with lessons, the glossary) | Output tokens | Code is exact where the model would guess |
| The deadline conflict and the standard assumptions (session length, missing experience) are worked out in code | Output tokens | Code uses the real numbers |
| A lesson limit from the learner's time is sent with the request | Output tokens on long plans | Extra lessons are cut, optional ones first |
| The system prompt is short (about 540 tokens) and never changes between learners; learner details go in a user message of about 75 tokens | Input tokens; lets providers cache the prompt | The full rules stay in this file, and the prompt names the sections it follows |
| The learner summary lists topic titles by skill check status, not the curated catalogue | Input tokens | The model only needs to know what to leave out or recap |
| At most 3 curated project ideas, each cut to 160 characters | Input tokens | The model adapts the best fit |
| Short but readable output keys (`can`, `min`, `needs`) and a shape in the prompt instead of a worked example | Output and input tokens | JSON mode on Groq, and code checks every field |
| Small problems are repaired in code; the model is asked again only when nothing is usable, and never after every provider failed | Retry calls | Every repair is recorded for review |
| Short reasoning (`reasoning_effort: low`) on gpt-oss models | Output tokens and time | The outline is structured, not open-ended |
| Lessons are written one at a time when opened, not all at sign-up | Calls for lessons a learner never reaches | Each lesson can use the learner's latest results |

## 11. Quality review

Generated plans and lessons reach learners without approval. Review happens afterwards, in the Django admin page, on a small sample plus anything flagged. It is needed because section 10 catches broken structure, not wrong content: a wrong explanation, an example that prints something else, or a quiz whose stored answer is wrong. Beginners can't spot these. Review is also how the team learns what to fix in the prompts.

### Four layers

| Layer | What it does | Enforced by | Status |
| --- | --- | --- | --- |
| 1. Labels and reports | AI-written parts are labelled. Learners can report a problem with their plan (`PlanFeedback`); v1 adds reporting a single lesson | Code | Built (plan); v1 (lesson) |
| 2. Automatic flags | Flag a lesson when a Python example doesn't parse (checked with `ast`; AI or learner code is never run on the server), when almost every learner misses the same question (its answer is likely wrong), or when it was regenerated many times | Code | v1 |
| 3. Lesson feedback | Thumbs up or down at the end of each lesson; thumbs down flags it | Code | v1 |
| 4. Weekly review | A person reviews every flagged or reported lesson plus about 10 random ones, using the checklist | Team | v1 |

### The review page (Django admin)

- A list of generated lessons and plan outlines with filters: Reported, Flagged, Thumbs down, Not reviewed, Prompt version, and a Random sample view.
- Each item has a review status (Not reviewed, OK, Problem), notes, reviewer, review date and the reason it was flagged.
- Actions: mark OK; mark Problem with a note; Regenerate for this learner (they see the new version next time and aren't penalised for answers to the old quiz).
- No separate tool or dashboard. Review lives in the admin page curators already use.

### The weekly routine

- One person a week, on a rotation, for about 30 to 60 minutes.
- Review every Reported, Flagged and Thumbs-down item first, then about 10 random lessons.
- When a problem repeats, fix the prompt (it fixes every future lesson) and commit it with a new prompt version.
- Listed in the README's Regular jobs next to `check_links` and `send_reminders`, so CompSAt can run it after handover.
- Track the problem rate per prompt version (Problems ÷ reviewed). When it stays low for about four weeks, stop the random sample and review only flagged and reported items.

### Review checklist

- Assumptions and any conflict are stated at the top.
- Setup comes first and ends with its check.
- No lesson needs an idea that hasn't been taught yet.
- Lessons fit the depth table: ideas, key terms, minutes.
- Every lesson has an example, a try-it task, resources and a mini-check.
- Explanations and examples are correct. Run every code example.
- Quiz answers are right, and questions only cover what was taught.
- Resources are on the allowed list and fit the level.
- The project uses what the plan taught and matches the learner's goal.
- Tone is plain and encouraging; English or Taglish matches the learner.

## 12. What changes in the app (v1)

| Area | Change |
| --- | --- |
| `docs/plan-framework.md` | This file |
| `learning/prompts/` | `outline.md` (built, `outline-2`) and `lesson.md`: the short prompts, each naming the sections it follows, with a version |
| `learning/outline.py` | Built: builds the outline request, checks and repairs the reply, saves it. Shadow mode (`AI_OUTLINES`) saves one with each AI-tailored plan |
| `learning/tailoring.py` | When lessons ship: the outline replaces topic selection; the curated plan stays as the fallback |
| New models | Built: `PlanOutline` (outline JSON, repairs, model, prompt version, tokens, review fields). With lessons: `PlanModule` and `GeneratedLesson` (lesson JSON, links, model, prompt version, level, review fields) |
| `draft_outline` command | Built: try the outline prompt on a learner or made-up answers, see the repairs and token counts |
| Lesson page | Generate on first open, then show the saved lesson; regenerate after a low score |
| Quiz and grading | Grade the lesson's own questions with today's grading rules and score bands |
| Review (admin) | Built for outlines: readable outline, review status, notes, reviewer, filters, 10 random sample, Mark OK / Mark problem. With lessons: flag reason and a Regenerate action |
| Flags and feedback | Example parse check, most-missed question, regeneration count; thumbs up or down and report on each lesson |
| Finish screen | Glossary from the saved lessons' key terms |
| Settings | `AI_LESSON_DAILY_LIMIT` next to `AI_DAILY_LIMIT` and `AI_INTAKE_DAILY_LIMIT` |
| README | Replace "CodeAgapay doesn't write tutorials", update the plan diagram, add the weekly review to Regular jobs |

## 13. Later

| Item | Why it waits |
| --- | --- |
| **Retrieval:** save pages from the allowed sites and have the AI teach from that text, citing it | Needs fetching, storage and licence checks (MDN is CC-BY-SA; W3Schools doesn't allow copying) |
| **Lesson library:** promote reviewed or well-rated generated lessons for later learners to reuse | Needs ratings and enough real lessons; v1 saves lessons in a form that allows it |
| Module quizzes, final check, review lessons, catch-up sessions | Keep v1 small |
| Skip a lesson at 85% before it | Needs a pre-check per lesson |
| AI grading of written answers | Needs a reliable rubric and costs an AI call per answer |
| Spaced repetition instead of the fixed 7-day review | Known issue; separate change |
| Time per session question in onboarding | 30-minute default until the team decides |

## 14. Team decisions

### Decided (9 November 2026)

1. The AI creates the whole learning plan and its lessons, guided by this framework. Pre-approved content blocks are not used in v1.
2. This framework and its v1 plan are the implementation plan.
3. Generated lessons reach learners before anyone reviews them, labelled as AI-written. Review happens afterwards, weekly, in the Django admin page (section 11).
4. The language-learning parts of version 1 stay removed. Only Taglish compatibility is kept (section 6).

### Still open

1. Confirm the allowed list (section 9) and who checks each row.
2. Set the review rotation.
3. Choose the daily lesson-generation limit per learner.
4. Decide what learners see on non-Python tracks when the AI is unavailable.
5. Keep 30 minutes as the default session length, or add the question to onboarding.

## Appendix A. Output shapes

Shortened. The full JSON schemas live in code next to the validation; update this appendix when they change.

Outline (step 2):

```json
{
  "goal": "what the learner can do at the end",
  "level": "beginner | intermediate | advanced",
  "assumptions": ["30-minute sessions (not asked)"],
  "conflict": "empty, or the problem and a realistic version",
  "modules": [{
    "title": "...", "goal": "one sentence", "milestone": "you can now ...",
    "stuck_path": ["reread the key terms", "try the video instead"],
    "lessons": [{
      "key": "m1-l1", "title": "...", "you_will_be_able_to": "...",
      "minutes": 25, "importance": "core | optional",
      "kind": "foundation | recap | core", "needs": ["earlier lesson keys"]
    }]
  }],
  "project": {
    "title": "...", "description": "...",
    "steps": [{"module": 1, "text": "one step per module; code sets its week from that module"}],
    "done_when": ["3 to 5 checks"], "idea": 0
  },
  "next_steps": ["..."]
}
```

Lesson (step 3):

```json
{
  "warm_up": ["question"],
  "key_terms": [{"term": "...", "definition": "..."}],
  "why_it_matters": "...",
  "explanation": "...",
  "examples": [{"code": "...", "output": "...", "note": "..."}],
  "try_it": {"prompt": "...", "starter_code": "...", "sample_answer": "...", "checklist": ["..."]},
  "resources": [{"name": "...", "role": "primary | optional", "url": "allowed site, or omitted", "search_phrase": "..."}],
  "mini_check": ["question"]
}
```

A question:

```json
{
  "format": "multiple_choice | fill_blank | self_check",
  "skill": "recall | apply | explain",
  "prompt": "...",
  "choices": ["..."], "correct_index": 0,
  "accepted_answers": ["..."],
  "explanation": "one sentence"
}
```

## Appendix B. Changes from version 1

| Version 1 | Version 2 |
| --- | --- |
| Any topic | CodeAgapay's coding paths and tracks only |
| One AI call writes the whole plan | Outline at sign-up; each lesson when first opened |
| Rules enforced by the prompt | Each rule says whether the prompt, the code or the team enforces it |
| Five topic types, including spoken languages | One: tool or technical skill. Setup stays curated. Only Taglish compatibility kept |
| Any question format | Only auto-gradable formats; "explain" is an ungraded self-check |
| 40+ general resources, some paid | Allowed list of free coding resources, checked in code |
| camelCase JSON schema | Shorter shapes in appendix A, matched to the app |
| No review process | Review after release, weekly, in the Django admin page |
| No implementation status | Every rule marked Built, v1 or Later |
