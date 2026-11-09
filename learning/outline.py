"""AI-written plan outlines (docs/plan-framework.md, sections 2 and 5).

The AI writes modules and lesson titles only; lessons are written later, one by one.
To keep each call small, the code does everything it can by itself: weeks, totals,
module progress, stuck paths, setup and the deadline check never cost tokens. The
system prompt never changes (so providers can cache it), and everything about the
learner goes in a short user message.

Replies are repaired rather than retried: bad minutes are clamped, unknown lesson
numbers dropped, long modules split and extra lessons cut. Only a reply with no
usable lessons is asked for again, once.
"""

import re
import unicodedata
from pathlib import Path
from types import SimpleNamespace

from assistant.service import ask_model_json, language_note
from content.models import ProjectIdea
from diagnose.models import TopicMastery

from .models import PlanOutline
from .planner import assign_weeks, milestone_weeks

PROMPTS = Path(__file__).parent / "prompts"

LEVEL_MINUTES = {"beginner": (15, 30), "intermediate": (25, 45), "advanced": (30, 60)}
KINDS = {"foundation", "recap", "core", "optional"}
DEFAULT_LESSON_LIMIT = 20
MAX_LESSONS = 30
MAX_MODULE_LESSONS = 5
SESSION_MINUTES = 30  # Not asked in onboarding yet (framework section 3).
MAX_TOKENS = 3500  # About 2,000 for 30 lessons, plus room for short reasoning.
MAX_IDEAS = 3

# Shown with every module, so the model never spends tokens on them (framework section 6, stuck path).
STUCK_PATH = [
    "Reread the key terms, then try the example again.",
    "Try the lesson's other resource, in a different format.",
    "Ask Agapay for a hint.",
    "Skip the optional parts and come back later.",
]


def load_prompt(name="outline"):
    """A system prompt and its version, from learning/prompts/<name>.md."""
    text = (PROMPTS / f"{name}.md").read_text(encoding="utf-8")
    header, _, body = text.partition("\n\n")
    match = re.search(r"^version:\s*(\S+)", header, re.MULTILINE)
    return body.strip(), match.group(1) if match else "unknown"


def learner_level(profile):
    """The depth table column. Onboarding has no advanced answer, so it tops out at intermediate."""
    if profile.experience == profile.Experience.COMFORTABLE:
        return "intermediate"
    return "beginner"


def outline_tracks(profile):
    """Every track of the learner's path, live or not: the AI writes the lessons, so none need curated topics."""
    tracks = profile.path.ordered_tracks() if profile.path_id else []
    if profile.track and profile.track not in tracks:
        tracks.insert(0, profile.track)
    return tracks


def lesson_limit(profile, level):
    """How many lessons fit the learner's time, so the model never writes more than can be used."""
    if not (profile.hours_per_week and profile.target_weeks):
        return DEFAULT_LESSON_LIMIT
    low, high = LEVEL_MINUTES[level]
    budget = profile.hours_per_week * 60 * profile.target_weeks
    return max(4, min(budget // ((low + high) // 2), MAX_LESSONS))


def project_ideas(profile):
    """Curated ideas for the path's first track, for the model to adapt. Only a few, to save tokens."""
    first_track = outline_tracks(profile)[:1]
    return list(ProjectIdea.objects.filter(track__in=first_track, is_active=True)[:MAX_IDEAS])


def _skill_summary(profile):
    if profile.pk is None:
        return {}
    by_status = {}
    for mastery in TopicMastery.objects.filter(learner=profile).select_related("topic").order_by("topic__order"):
        by_status.setdefault(mastery.status, []).append(mastery.topic.title)
    return by_status


def build_messages(profile, project_idea, ideas=()):
    """The system prompt (fixed) and a short user message with only what this plan needs."""
    system, version = load_prompt()
    level = learner_level(profile)
    low, high = LEVEL_MINUTES[level]
    tracks = ", ".join(t.name for t in outline_tracks(profile))
    path = profile.path.title if profile.path_id else "Learn to code"
    time = f"{profile.hours_per_week or 2} hours a week, about {SESSION_MINUTES}-minute sessions"
    if profile.target_weeks:
        time += f", aiming to finish in {profile.target_weeks} weeks"
    lines = [
        f"Path: {path} ({tracks})",
        f"Level: {level} (lesson minutes {low}-{high})",
        f"Time: {time}",
        f"Lesson limit: {lesson_limit(profile, level)}",
        f"Goal: {profile.goal_text or 'not given'}",
        f"Project idea: {project_idea or 'none, suggest one'}",
    ]
    if profile.hint_style:
        lines.append(f"Learns best from: {profile.get_hint_style_display().lower()}")
    if language_note(f"{profile.goal_text} {project_idea}"):
        lines.append("Language: Taglish")
    skills = _skill_summary(profile)
    Status = TopicMastery.Status
    for status, label in [
        (Status.DEMONSTRATED, "Showed on the skill check (leave out)"),
        (Status.EMERGING, "Partly there (recap)"),
        (Status.NEEDS_REVIEW, "Knew before (recap)"),
        (Status.NOT_YET, "To work on"),
    ]:
        if skills.get(status):
            lines.append(f"{label}: {', '.join(skills[status])}")
    if ideas:
        lines.append("Project ideas:")
        lines.extend(f"{i}. {idea.title}: {idea.brief[:160]}" for i, idea in enumerate(ideas, 1))
    messages = [{"role": "system", "content": system}, {"role": "user", "content": "\n".join(lines)}]
    return messages, version


def clean_chars(text):
    """Replace characters models emit that look right but break copying, search and grading.

    Unicode hyphens become "-". Invisible format characters (zero-width spaces and the like,
    Unicode category Cf) become spaces: models put them where a space belongs, so the words
    otherwise show up glued together ("needfor").
    """
    return "".join(
        "-" if ch in "\u2010\u2011" else " " if unicodedata.category(ch) == "Cf" else ch for ch in str(text)
    )


def _text(value, limit):
    """Prose from the model on one line. Never used for code."""
    text = " ".join(clean_chars(value or "").split())
    # A full stop with no space before the next sentence ("activities.I-save"). Only lowercase
    # then uppercase, so file names and versions ("page.html", "3.13") are left alone.
    return re.sub(r"(?<=[a-z])\.(?=[A-Z])", ". ", text)[:limit]


def _list(value):
    """A list from the reply, or an empty one when the model sent something else."""
    return value if isinstance(value, list) else []


def _int(value, default=None):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def parse_outline(data, profile, ideas=()):
    """Check and repair the model's outline. Returns (outline, repairs), or (None, repairs) if unusable.

    Everything the code can work out (numbers, keys, weeks, totals, progress, stuck
    path, the deadline conflict) is added here rather than asked of the model.
    """
    repairs = []
    level = learner_level(profile)
    low, high = LEVEL_MINUTES[level]
    limit = lesson_limit(profile, level)

    # 1. Collect lessons, keeping the model's numbering so "needs" and project steps can be mapped.
    modules, raw_number = [], 0
    for m, module in enumerate(_list(data.get("modules")), 1):
        if not isinstance(module, dict):
            continue
        lessons = []
        for lesson in _list(module.get("lessons")):
            raw_number += 1
            if not isinstance(lesson, dict) or not _text(lesson.get("title"), 150):
                repairs.append(f"Dropped lesson {raw_number}: no title")
                continue
            minutes = _int(lesson.get("min"), (low + high) // 2)
            if not low <= minutes <= high:
                repairs.append(f"Lesson {raw_number}: {minutes} min clamped to {low}-{high}")
                minutes = min(max(minutes, low), high)
            kind = str(lesson.get("kind") or "").strip().lower()
            if kind not in KINDS:
                kind = "core"
            lessons.append({
                "raw": raw_number,
                "title": _text(lesson.get("title"), 150),
                "can": _text(lesson.get("can"), 200),
                "minutes": minutes,
                "kind": kind,
                "needs_raw": [n for n in (_int(x) for x in _list(lesson.get("needs"))) if n],
            })
        if lessons:
            modules.append({
                "title": _text(module.get("title"), 150) or f"Module {m}",
                "goal": _text(module.get("goal"), 200),
                "milestone": _text(module.get("done"), 200),
                "lessons": lessons,
                "raw_module": m,
            })
    if not modules:
        repairs.append("No usable lessons")
        return None, repairs

    # 2. Stay within the lesson limit: cut optional lessons from the end first, then the last lessons.
    flat = [lesson for module in modules for lesson in module["lessons"]]
    if len(flat) > limit:
        repairs.append(f"{len(flat)} lessons cut to the limit of {limit}")
        extra = len(flat) - limit
        for lesson in reversed([x for x in flat if x["kind"] == "optional"]):
            if extra == 0:
                break
            lesson["cut"] = True
            extra -= 1
        for lesson in reversed(flat):
            if extra == 0:
                break
            if not lesson.get("cut"):
                lesson["cut"] = True
                extra -= 1
        for module in modules:
            module["lessons"] = [x for x in module["lessons"] if not x.get("cut")]
        modules = [m for m in modules if m["lessons"]]

    # 3. Split modules longer than the framework allows.
    split = []
    for module in modules:
        chunks = [module["lessons"][i:i + MAX_MODULE_LESSONS] for i in range(0, len(module["lessons"]), MAX_MODULE_LESSONS)]
        if len(chunks) > 1:
            repairs.append(f"Split \"{module['title']}\" into {len(chunks)} modules")
        for part, chunk in enumerate(chunks, 1):
            title = module["title"] if part == 1 else f"{module['title']} (part {part})"
            split.append({**module, "title": title, "lessons": chunk,
                          "milestone": module["milestone"] if part == len(chunks) else ""})
    modules = split

    # 4. Number lessons, map "needs" to earlier lessons only, and assign weeks.
    flat = [lesson for module in modules for lesson in module["lessons"]]
    number_of = {lesson["raw"]: n for n, lesson in enumerate(flat, 1)}
    weeks = assign_weeks([SimpleNamespace(estimated_minutes=x["minutes"]) for x in flat], profile.hours_per_week)
    for n, (lesson, week) in enumerate(zip(flat, weeks), 1):
        needs = sorted({number_of[r] for r in lesson.pop("needs_raw") if r in number_of and number_of[r] < n})
        lesson.update(number=n, key=f"L{n}", week=week, needs=[f"L{x}" for x in needs])
        if not lesson["can"]:
            repairs.append(f"Lesson {n} has no \"You will be able to\" line")
    keys_by_module = {}  # The model's module number -> its lesson keys, across any split parts.
    for i, module in enumerate(modules, 1):
        module.update(number=i, progress=f"Module {i} of {len(modules)}", stuck_path=STUCK_PATH)
        keys_by_module.setdefault(module.pop("raw_module"), []).extend(x["key"] for x in module["lessons"])
        for lesson in module["lessons"]:
            lesson.pop("raw")

    # 5. The project. Each step names a module (models miscount lesson numbers, not modules);
    # its week is the week that module ends.
    week_of = {lesson["key"]: lesson["week"] for lesson in flat}
    project, idea = _parse_project(data.get("project"), keys_by_module, week_of, ideas, repairs)

    # 6. What the code knows better than the model: assumptions and the deadline.
    total_minutes = sum(x["minutes"] for x in flat)
    last_week = max(weeks)
    assumptions = [f"Sessions of about {SESSION_MINUTES} minutes (we didn't ask)."]
    if not profile.experience:
        assumptions.append("A complete beginner (experience not given).")
    assumptions += [_text(a, 200) for a in _list(data.get("assumptions"))[:5] if _text(a, 200)]
    conflict = _text(data.get("conflict"), 400)
    if profile.target_weeks and last_week > profile.target_weeks and not conflict:
        conflict = (f"This plan needs about {last_week} weeks at {profile.hours_per_week or 1} hours a week, "
                    f"more than the {profile.target_weeks} weeks you have. More hours a week, or a later date, would fit it.")

    outline = {
        "goal": _text(data.get("goal"), 300) or profile.goal_text,
        "level": level,
        "assumptions": assumptions,
        "conflict": conflict,
        "lessons_total": len(flat),
        "minutes_total": total_minutes,
        "weeks_total": last_week,
        "modules": modules,
        "project": project,
        "idea": idea.pk if idea else None,
        "next_steps": [_text(x, 200) for x in _list(data.get("next"))[:5] if _text(x, 200)],
    }
    return outline, repairs


def _parse_project(project, keys_by_module, week_of, ideas, repairs):
    """The model's project, or a plain one built from the lessons when it is unusable."""
    idea = None
    if isinstance(project, dict):
        number = _int(project.get("idea"), 0)
        if 1 <= number <= len(ideas):
            idea = ideas[number - 1]
        steps = []
        for step in _list(project.get("steps"))[:6]:
            if not (isinstance(step, dict) and _text(step.get("text"), 300)):
                continue
            module = _int(step.get("module"))
            if module not in keys_by_module:
                repairs.append(f"Dropped project step for unknown module {step.get('module')!r}")
                continue
            steps.append({"module": module, "topics": keys_by_module[module], "text": _text(step.get("text"), 300)})
        done_when = [_text(c, 200) for c in _list(project.get("done_when"))[:6] if _text(c, 200)]
        if not done_when and idea is not None:
            done_when = list(idea.done_when)
        title, description = _text(project.get("title"), 200), _text(project.get("description"), 1000)
        if title and description and steps and done_when:
            return {"title": title, "description": description,
                    "milestones": milestone_weeks(steps, week_of), "done_when": done_when}, idea
    repairs.append("Project unusable; used a plain one")
    last = max(week_of.values())
    return {
        "title": "Your mini project",
        "description": "Build one small project and grow it a little each week using what you just learned.",
        "milestones": [{"topics": [], "week": week, "text": "Add something that uses this week's lessons."}
                       for week in range(1, last + 1)],
        "done_when": ["It runs without errors.", "It uses something from every week.",
                      "You can explain each part to a friend."],
    }, idea


def generate_outline(profile, project_idea="", plan=None, save=True):
    """Ask the AI for an outline, check it, and save it for review.

    Returns the PlanOutline (unsaved when save=False), or None when the AI is
    unavailable or replied with nothing usable twice. Learners don't see outlines
    yet; they are reviewed in admin until lesson generation ships.
    """
    ideas = project_ideas(profile)
    messages, version = build_messages(profile, project_idea, ideas)
    repairs, usage = [], {}
    earlier_problems = []
    for attempt in range(2):
        attempt_usage = {}
        data = ask_model_json(messages, max_tokens=MAX_TOKENS, usage=attempt_usage)
        for field in ("prompt_tokens", "completion_tokens"):
            usage[field] = (usage.get(field) or 0) + (attempt_usage.get(field) or 0)
        usage["model"] = attempt_usage.get("model", usage.get("model", ""))
        if data is None:
            return None  # Every provider failed; asking again would only fail again.
        outline, repairs = parse_outline(data, profile, ideas)
        if outline is not None:
            break
        earlier_problems = ["Asked again: the first reply had no usable lessons"]
    else:
        return None
    repairs = earlier_problems + repairs
    record = PlanOutline(
        learner=profile, plan=plan, data=outline, repairs=repairs,
        prompt_version=version, model=usage.get("model", ""),
        prompt_tokens=usage.get("prompt_tokens") or None, completion_tokens=usage.get("completion_tokens") or None,
    )
    record.raw = data  # The model's reply before checks, for draft_outline --raw. Not saved.
    if save:
        record.save()
    return record
