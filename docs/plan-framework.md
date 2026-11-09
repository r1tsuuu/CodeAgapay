# CodeAgapay AI Learning Plan Framework

Version 2.1, accepted by the team on 9 November 2026. Steps 2 to 5 are built behind `AI_PLANS` (prompts `outline-2` and `lesson-16`); with it off, learners get the curated plan.

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
| 2. Outline | After the learner confirms | One AI call writes the outline (section 5). Code checks and saves it. Code assigns weeks from hours per week | Built. With `AI_PLANS` it becomes the learner's plan; otherwise `AI_OUTLINES` saves it for review only | `learning/outline.py`, `learning/prompts/outline.md`, `diagnose/views.py` |
| 3. Lesson | First open of a lesson | One AI call writes it (section 6). Code checks and saves it; later visits show the saved lesson | Built behind `AI_PLANS`: a "writing your lesson" page, then the saved lesson. Counted against `AI_LESSON_DAILY_LIMIT` | `learning/lessons.py`, `learning/ai_views.py` |
| 4. Check | End of each lesson | Code grades the mini-check and applies the score bands (section 7) | Built behind `AI_PLANS` | `learning/ai_plan.py` `grade_check` |
| 5. Adapt | After a low score | The lesson is regenerated with a different explanation, examples and questions; the old version is kept for review | Built: after a miss the learner can ask for it explained another way, aimed at the questions they missed | `learning/lessons.py`, `learning/ai_views.py` |
| Fallback | AI off, over its limit, or two bad replies | Today's curated plan when the path has curated topics; otherwise a page to try again | Built | `diagnose/views.py` `_build_ai_plan` |

**Fallback on paths without curated topics:** only Python has curated topics (HTML and CSS are drafted in `content/drafts/`). When the AI can't write a plan for another path, the plan page offers to try again. With `AI_PLANS` on, a path needs no curated topics to be offered.

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
| Computer (new in v2) | "What will you use to learn?": Windows, Mac, Linux, Chromebook, phone or tablet, or not sure (`LearnerProfile.device`) | Built | Setup guides use its shortcuts, file manager, install steps and commands; lessons get "Computer: A Mac". On a phone or Chromebook, install-based options say they need a computer, and the no-install way is recommended when there's no curated guide |

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
| Setup | Every AI plan opens with a required setup step (`outline.setup_lesson`); no lesson opens until the learner chooses an option. The options, in order: the track's curated guide (`SetupStep`s and `Track.setup_check`), always tagged Recommended; VS Code step by step, with one project folder named from the project (`codeagapay-event-page`), tagged Recommended only when there is no curated guide; and a no-install way (CodePen for web, Google Colab for Python) where one exists. The code picks the tools, and the install steps for VS Code (web, Python, Java), CodePen and Google Colab are built-in guides with official links (`learning/setup_guides.py`): downloading, extensions, the folder, opening it, the first file, saving, running it and reopening the project. The AI writes only the why and the first-file check for the learner's project, and writes install steps only for tracks without a built-in guide. The learner's choice (`PlanOutline.setup_choice`) is sent with every later lesson, which follows it. When the AI can't write the setup page, the curated guide can still be chosen. Learners can change their setup method at any time from the plan page; lessons not yet opened follow the new setup, and the learner can ask to update lessons already written, each rewritten the next time it's opened (one daily lesson each, with a warning; done one at a time so no page waits on many AI calls) | Built |
| Foundations | Basic building blocks; recaps when the skill check showed them | v1 |
| Modules | 3 to 5 lessons each, simple to complex, each with a one-sentence goal, a milestone ("you can now...") and a stuck path | v1 |
| Lessons (titles only) | Title, "You will be able to", minutes, core or optional, lessons it needs | v1 |
| Project | One project tied to the goal, with weekly steps and "done when" checks, adapted from a curated `ProjectIdea` when one fits | Built |
| Next steps and glossary | What to learn next; every key term from the saved lessons, in order, on the finish screen | Built (`lessons.glossary`); the finish screen shows it with the lesson page |

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
| Warm-up | 1 to 2 ungraded questions on the previous lesson, preferring ones the learner missed; none in the first lesson | Built for curated topics (`journey.warm_up`) and generated lessons (`lessons.warm_up`, taken from the previous lesson's saved questions, so no tokens). Preferring missed ones comes with the lesson page |
| Key terms | Up to 3 for beginners (5 intermediate, 7 advanced), each with a plain definition. A definition uses only everyday words and terms already taught; a new idea it needs gets one short plain clause, never a chain of new terms (not "declares the document as HTML5", but "tells the browser this is a modern HTML page") | Built (`Topic.clean` allows 3; the rule is in `prompts/lesson.md`) |
| Why it matters | The problem this solves, before the how | Built |
| Explanation | At the depth for the level; no internals or history for beginners. Paragraphs of 2 or 3 sentences, one idea each; longer ones are split at sentence ends in code. Several parts, steps or options become a list (bullets, or numbers for steps in order) | Built |
| Formatting | Code is colored like an editor, by each example's language (Pygments, in `learning/templatetags/lesson_format.py`). Code words in sentences are wrapped in backticks by the AI, and HTML tags are found in code; both show bold and colored. Things to click or choose (buttons, menus, settings) are wrapped in double asterisks and show in bold, in the normal text colour; keyboard shortcuts (Ctrl+S, Cmd+Shift+X) are found in code and show as key caps. No tokens are spent on either | Built |
| Example | Worked code with its exact output. Two at beginner level: one simple, one real-world, ideally from the learner's path | v1 (curated topics have one) |
| Try it yourself | Copy an example, change it, then build something small; no files, internet or installs for beginners | Built (`PracticeTask`) |
| How to try it | The AI names the one file the task uses (`try.file`). The app adds the steps to create, save and see it in the learner's setup and on their computer (VS Code with Live Server or Run, the team's guide, CodePen or Colab), from `setup_guides.try_steps`. Open for beginners, a collapsed reminder for others; examples point to the same steps | Built |
| Resources | 1 primary and up to 2 optional, from section 9 only | v1 |
| Mini-check | 2 to 3 auto-graded questions (1 if sessions are under 20 minutes) | Built |

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
| Same rule for generated lessons, detected from the learner's goal | Prompt + Code | Built | `lessons.spec_from_outline`, `prompts/lesson.md` |
| Code, keywords, function names and error messages stay in English | Prompt | Built | `prompts/lesson.md` |
| Taglish the way Filipino students mix it, not formal Tagalog; 2 or 3 sample explanations in the prompt | Prompt | Built (2 samples) | `prompts/lesson.md` |
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
| Mini-check | End of every lesson | Built (AI lessons) |
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
| 50% to 69% | Suggest another resource and retake. On AI lessons, the same questions can be retried, or the lesson rewritten with new questions | Built |
| Below 50% | Re-teach: the lesson rewritten with a different explanation and examples, aimed at the missed questions | Built (AI lessons, on request). Checking for a skipped earlier lesson is Later |
| Two misses | Mark shaky, continue the plan, bring it back as a review | Built |
| 85% before a lesson | Skip it but still show its key terms (today a curated topic is skipped by passing its quiz at 70%) | Later |

A failed check never blocks the learner for good; there is always a next step. *Code. Built.*

## 8. Adapting to the learner

| Signal | What changes | Status |
| --- | --- | --- |
| Skill check result | Shown topics are skipped; partly-there topics become recaps | Built |
| Experience and results | Pick the depth table column | v1 |
| Low score on a lesson | Rewrite it: new explanation, new examples, new questions, aimed at what was missed | Built |
| Missed questions | Come back first in the next warm-up (`journey.warm_up`) and the retake | Built for curated topics; v1 for generated lessons |
| What helps when stuck | Shapes hints today; v1 also shapes lesson examples and resource types | Built |
| Pace change | Weeks recomputed, progress kept (`planner.repace_plan`) | Built |
| Passed topics | Come back for a short review after 7 days (`journey.REVIEW_AFTER_DAYS`) | Built |
| Missed sessions | Progress never resets; opt-in reminder emails (`learning/reminders.py`) | Built |
| Plans over 2 weeks | One catch-up session a week; a review lesson after every 2 modules | Later |

## 9. Resources and grounding

| Rule | Enforced by | Status |
| --- | --- | --- |
| Keep a link only if its site is on the allowed list; otherwise drop the URL and keep the name and a search phrase. MDN and the Python docs get a site search link, which always works | Code | Built (`lessons.allowed_link`, `ALLOWED_LINKS`) |
| Give the AI the curated links the app already has for the subject, and prefer them | Prompt | v1 |
| Free resources only; paid ones are not on the list | Team | v1 |
| Match the learner's level; no advanced docs for beginners | Prompt | v1 |
| Setup uses official sources and stays curated | Team | Built |
| Resources support the lesson; they never replace its explanation | Prompt | Built |
| Official documentation (Python docs, MDN, VS Code docs, Java docs, SQLite and PostgreSQL docs) is used when learning sites don't cover something well. Each official-docs link comes with a one-line "how to read it" tip (which part of the page to look at, what to skip); one without a tip is flagged for review | Prompt + Code | Built (`lessons.OFFICIAL_DOCS`) |
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
| VS Code docs | code.visualstudio.com/docs | The editor: settings, extensions, running code | Beginner to advanced | |
| Java docs | dev.java, docs.oracle.com/en/java | Learning Java (dev.java) and the Java API reference | Beginner to advanced | |
| SQL docs | sqlite.org, postgresql.org/docs | SQL statements and functions | Intermediate to advanced | |

Removed from version 1: paid or mostly paid (Brilliant, Udemy, Google certificates, Codecademy Pro, LeetCode premium) and non-coding (Duolingo, Forvo, Easy Languages, language exchange apps, Kahoot, Investopedia, Desmos, Wolfram Alpha, OpenStax, Project Gutenberg, Open Library). YouTube is allowed by channel plus a search phrase until specific videos are checked.

## 10. Checks on every AI reply

These run in code before anything is saved or shown. They are what make AI-written plans safe to show without approving each one first.

| Check | If it fails | Status |
| --- | --- | --- |
| Valid JSON in the expected shape (appendix A) | Try the next provider; for an outline with no usable lessons, ask once more, then fall back | Built (`ask_model_json`, `outline.generate_outline`) |
| Outline: lessons have titles; minutes within the depth table; known kinds | Repair in code (drop, clamp, default) and record the repair; no extra AI call | Built (`outline.parse_outline`) |
| Lesson: an explanation, an example, a task and 2 gradable questions | Ask once more, then give up (the learner sees a try-later message) | Built (`lessons.parse_lesson`) |
| Lessons only need earlier lessons | Drop references to later or unknown lessons | Built (outline) |
| Every question is gradable: a multiple choice with distinct choices and a valid answer, or a blank with ___ and accepted answers | Drop it; ask again if fewer than 2 remain | Built |
| Every link is on the allowed list | Remove the URL, keep the name and search phrase | Built |
| No link to another language's docs (MDN in a Python lesson, the Python docs in an HTML lesson) | Drop that resource; add the lesson language's own docs if none is left | Built (`lessons.LANGUAGE_SITES`) |
| Text within length limits; no HTML or scripts | Trim or strip | Built for trimming |
| Daily limits per learner | Plans: build without AI (`AI_INTAKE_DAILY_LIMIT`). Lessons: show a try-tomorrow message (`AI_LESSON_DAILY_LIMIT`, default 12) | Built |

AI providers: Groq first (`GROQ_PLAN_MODEL`, then `GROQ_MODEL`), Cloudflare Workers AI as backup. *Code. Built.* Plans and lessons are written inside a page request, which the server ends after 60 seconds (`gunicorn.conf.py`); each AI call may take up to 30 seconds (`AI_PLAN_CALL_TIMEOUT`) and all of a request's calls together stay within 50 (`AI_REQUEST_BUDGET`), so a slow model falls back in time instead of the page failing. *Code. Built.* Each saved outline records the model, prompt version and token counts (`PlanOutline`). *Code. Built.* Lessons will too. *v1.*

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
| 1. Labels and reports | AI-written parts are labelled. Learners report a problem with a curated plan (`PlanFeedback`) or, on an AI lesson, with a thumbs down and an optional note | Code | Built |
| 2. Automatic flags | Flag a lesson when a Python example or task answer doesn't parse (checked with `ast`; code is never run on the server) or a blank's answer is long or shown in its own question, or an HTML example or task uses a tag the lesson doesn't explain. Built (`GeneratedLesson.flags`, filter **Flagged**). With the lesson page: when almost every learner misses the same question, or it was regenerated many times | Code | Built (parse, long blank); v1 (the rest) |
| 3. Lesson feedback | Thumbs up or down at the end of each lesson; thumbs down flags it, with the learner's note (`LessonProgress.rating`) | Code | Built |
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
- Key term definitions and the explanation bring in no new term without a short plain meaning.
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
| `learning/prompts/` | `outline.md` (built, `outline-2`) and `lesson.md` (built, `lesson-16`): the short prompts, each naming the sections it follows, with a version |
| `learning/outline.py` | Built: builds the outline request, checks and repairs the reply, saves it. Shadow mode (`AI_OUTLINES`) saves one with each AI-tailored plan |
| `learning/tailoring.py` | When lessons ship: the outline replaces topic selection; the curated plan stays as the fallback |
| New models | Built: `PlanOutline` and `GeneratedLesson` (versions, current flag, flags), sharing `AIRecord` (JSON, repairs, model, prompt version, tokens, review fields). Modules stay inside the outline's JSON; a `PlanModule` table is only needed if the lesson page wants it |
| `draft_outline`, `draft_lesson` commands | Built: try each prompt on saved data or typed-in answers, see the repairs, flags and token counts |
| `learning/lessons.py` | Built: lesson request, checks and repairs, saving versions, regeneration, warm-ups and glossary from saved lessons |
| Lesson page | Built: `learning/ai_views.py` and `templates/learning/ai_*.html`, behind `AI_PLANS` |
| Quiz and grading | Built: `ai_plan.grade_check` uses the curated quiz's matching, pass mark and bands; progress in `LessonProgress` |
| Review (admin) | Built for outlines and lessons: readable view with answers, review status, notes, reviewer, filters (incl. **Flagged**), 10 random sample, Mark OK / Mark problem, and Regenerate for lessons (up to 5 at a time) |
| Flags and feedback | Example parse check, most-missed question, regeneration count; thumbs up or down and report on each lesson |
| Glossary | Built: on the AI plan page, from the saved lessons' key terms |
| Settings | Built: `AI_PLANS` and `AI_LESSON_DAILY_LIMIT` next to `AI_DAILY_LIMIT` and `AI_INTAKE_DAILY_LIMIT` |
| Gradual rollout | Built: **Gets AI plans early** on a learner's profile (`LearnerProfile.ai_plans_early`, with admin actions) gives AI plans to chosen learners while `AI_PLANS` is off; `AI_PLANS=True` then turns them on for everyone (`LearnerProfile.gets_ai_plans`) |
| Help panel on AI lessons | Built: hints grounded in the lesson's key terms and explanation; "Why is this wrong?" on missed check questions, never sending answers (`ai_plan.help_topic`) |
| Reminders and finish screen | Built for AI plans: reminders point to the next AI lesson (or setup); the finish page shows lessons done, moved on and skipped, the project, what to learn next and the glossary |
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
3. Confirm the daily lesson limit (default 12).
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
