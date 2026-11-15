# AI in CodeAgapay

The AI is optional. With no keys set, every feature still works from curated content and rules. This page lists every place the AI is used, what it may and may not do, and how it's limited. The detailed rules for AI-written plans are in [plan-framework.md](plan-framework.md).

## Providers

Groq first, then Cloudflare Workers AI, then (only if configured) a local model, all through the `openai` Python package with a custom base URL (`assistant/service.py`, `providers()`). Hints use `GROQ_MODEL` (small and fast); planning uses `GROQ_PLAN_MODEL`, falling back to `GROQ_MODEL` when the large one is busy. A rate-limited call is retried once if the provider asks for a wait of 3 seconds or less. Every call has a timeout, and a page's calls share a budget (`AI_REQUEST_BUDGET`, 50 s) that stays under gunicorn's 60 s limit.

### A local model (development only)

A model on your own computer can be the last provider, after Groq and Cloudflare. Use it for development and offline demos; the daily caps still apply. It can't run on Render: the free service has 512 MB of memory and no GPU.

```bash
brew install ollama            # or download it from ollama.com; LM Studio works too
ollama serve &                 # starts the local server on port 11434
ollama pull qwen2.5:7b         # about 4.7 GB; good at JSON and handles Filipino reasonably
```

Then in `.env`:

```bash
LOCAL_AI_URL=http://localhost:11434/v1
LOCAL_AI_MODEL=qwen2.5:7b
LOCAL_AI_TIMEOUT=45            # seconds for one hint
```

To use only the local model, also leave `GROQ_API_KEY` and the Cloudflare keys blank. Expect slower and weaker answers than Groq's larger models: small models follow the "hint, don't solve" rules less reliably, and writing a whole AI lesson can take a minute or more. `runserver` has no time limit, so for AI plans on a local model raise `AI_PLAN_CALL_TIMEOUT` and `AI_REQUEST_BUDGET` (for example to 170 and 180) in your local `.env` only; gunicorn on Render stops requests after 60 seconds.

## Where the AI is used

| Use | Prompt | Output checked by | Without AI |
| --- | --- | --- | --- |
| Agapay help panel | `assistant/service.py` `build_messages` | Markdown stripped; shown as plain text | The action's curated prompt plus the topic's tips and links |
| Practice feedback | `assistant/service.py` `build_practice_messages` | Plain text | The task's checklist |
| Reading a typed onboarding answer | `diagnose/onboarding.py` | Must name an existing path slug | The learner taps a choice |
| Tailoring a curated plan | `learning/tailoring.py` | Unknown topic slugs dropped; the planner adds prerequisites, orders and splits weeks | Every candidate topic and a template project |
| AI plan outline (`AI_PLANS`) | `learning/prompts/outline.md` | `learning/outline.py`: lesson limit, module size, dependencies only on earlier lessons; code assigns weeks | The curated plan, or a "try again" page |
| AI lesson (`AI_PLANS`) | `learning/prompts/lesson.md`, `lesson_setup.md` | `learning/lessons.py`: links kept only on the allowed list, questions kept only if gradable, code parsed and flagged | Retry page; the lesson isn't counted |
| Drafting for curators | `content/drafting.py` | Never writes links; refuses to write into a live track | Curators write it |

Every AI-written outline and lesson stores the prompt version, model and token counts, and can be reviewed in admin (Plan outlines, Generated lessons).

## Agapay, the help panel

Learners pick what they need. Each action becomes a rule in the system prompt (`ACTIONS` in `assistant/service.py`):

| Action | What Agapay does |
| --- | --- |
| Give me a hint | Three levels, one per click: (1) a direction, as one guiding question; (2) a strategy, the concept or approach in plain words; (3) a worked pattern on a similar but different example |
| Explain this concept | Plain words and one tiny example; doesn't solve their task |
| Help me debug | Reads their code and error, says where to look and why, asks what they expect; never writes the fixed code |
| Check my understanding | Asks one question and waits; doesn't answer it in the same message |
| Break this task down | 3 to 5 steps in words, no code |
| Show me the full solution | Only offered after hint 3, only after the learner confirms, and never on a quiz screen (the server turns it into hint 3 there). Explained step by step, framed as an explanation |
| Adjust my plan | **No AI.** Buttons for "move to later", links to pace and pause. Nothing changes until the learner presses one |
| Suggest a next project | **No AI.** The track's curated project ideas |

### What the model sees

Bounded on purpose (`build_messages`):

- The topic or AI lesson: title, language, summary, curated tips, resource titles (and, for AI lessons, their key terms and opening explanation).
- The learner's level (experience answer), hint style, and explanation language.
- Their question (500 characters), and when debugging their code (2,000) and error (500). On quiz screens: the quiz prompt and their current answer.

Never sent: names, emails, other learners' data, account history, earlier chats, accepted quiz answers, practice sample answers.

### Safety rules in every help prompt

- Stay on the topic; steer back gently if the question isn't about programming.
- Never give the exact answer to a quiz blank, whatever the action.
- Never give the full solution, except the confirmed solution action outside quizzes.
- Under 120 words (200 for a worked solution). Plain text: no markdown.
- Examples use everyday Filipino contexts when they fit: an org's members, a barangay event sign-up, a sari-sari store's stock, a class survey.
- Language: the learner's choice of English, Filipino or Taglish (`LearnerProfile.explain_language`, set in the panel or on the profile). With no choice, it matches the message: two or more common Tagalog words means Taglish. Lessons, plans and the interface stay in English; Filipino-language AI replies are not reviewed translations.

### Limits

All enforced on the server in `AIUsage`, with `select_for_update` so two requests can't both take the last message:

| Limit | Setting | Default |
| --- | --- | --- |
| Help panel and practice feedback messages per learner per day | `AI_DAILY_LIMIT` | 20 |
| AI-tailored plans per learner per day | `AI_INTAKE_DAILY_LIMIT` | 2 |
| AI-written lessons (and rewrites) per learner per day | `AI_LESSON_DAILY_LIMIT` | 12 |

A call that fails gives the message back. Help replies use `max_tokens=300`.

### Feedback

Each AI reply has Helpful, Not helpful and Report a problem. They're stored as `HelpFeedback` (where, action, mode, rating, and the learner's note for reports), never the question or reply. Review them in admin under **Help feedback**: filter on Not helpful or Reported, check the topic's tips and resources, tick Resolved. Plan reports go to **Plan feedback**; lesson ratings to **Generated lessons**.

## When the AI misbehaves

- **Wrong or unsafe replies:** tighten the rule in `build_messages` or `ACTIONS`, add a test in `assistant/test_actions.py`, and improve the topic's tips (they ground the model).
- **A prompt change for plans or lessons:** bump the `version:` line at the top of the prompt file, so admin shows which version wrote what.
- **Turning it off:** blank `GROQ_API_KEY` and the Cloudflare keys on Render. Everything falls back. To stop only AI-written plans, set `AI_PLANS=False`.

See [RUNBOOK.md](RUNBOOK.md#ai-provider-outage) for outages.
