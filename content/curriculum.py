"""The versioned curriculum files in content/curriculum/: load, validate, export and import.

    content/curriculum/curriculum.json      {"version": ..., "paths": [...]}
    content/curriculum/tracks/<slug>.json   one track with its topics and everything they hold

The shapes are the *_SHAPE dicts below, and `validate` holds the rules across files. docs/CURRICULUM.md
explains them for curators. Positions in a list are the order: the first topic is order 1.

Importing is safe on a live database. It never deletes a topic, and never deletes a check
question, quiz item or practice task that a learner has answered; it reports those instead.
"""

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path as FilePath

from django.db import transaction

from .models import (
    CurriculumRelease, Path, PathTrack, PracticeTask, ProjectIdea, QuizItem, Resource, SetupStep, SkillQuestion,
    Tip, Topic, Track,
)

CURRICULUM_DIR = FilePath(__file__).resolve().parent / "curriculum"
SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
RESOURCE_KINDS = {choice for choice, _ in Resource.Kind.choices}

# Each shape: field name -> (type, required). str fields may be empty unless listed in NONEMPTY.
PATH_SHAPE = {
    "slug": (str, True), "title": (str, True), "tagline": (str, True), "is_active": (bool, False),
    "tracks": (list, True), "language_reason": (str, False),
}
TRACK_SHAPE = {
    "slug": (str, True), "name": (str, True), "description": (str, False), "is_active": (bool, True),
    "setup_check": (str, False), "setup_steps": (list, False), "project_ideas": (list, False), "topics": (list, True),
}
TOPIC_SHAPE = {
    "slug": (str, True), "title": (str, True), "summary": (str, True), "why_it_matters": (str, False),
    "key_terms": (list, False), "explanation": (str, False), "example": (str, False), "example_output": (str, False),
    "intro_approved": (bool, False), "estimated_minutes": (int, True), "prerequisites": (list, False),
    "resources": (list, True), "tips": (list, False), "skill_questions": (list, False), "quiz_items": (list, False),
    "practice_tasks": (list, False),
}
RESOURCE_SHAPE = {
    "title": (str, True), "url": (str, True), "kind": (str, True), "estimated_minutes": (int, False),
    "is_active": (bool, False),
}
STEP_SHAPE = {"title": (str, True), "body": (str, True), "link": (str, False)}
IDEA_SHAPE = {"title": (str, True), "brief": (str, True), "done_when": (list, True), "is_active": (bool, False)}
QUESTION_SHAPE = {"prompt": (str, True), "code_snippet": (str, False), "choices": (list, True),
                  "correct_index": (int, True)}
QUIZ_SHAPE = {"prompt": (str, True), "accepted_answers": (list, True), "hint": (str, False),
              "explanation": (str, False), "case_sensitive": (bool, False)}
PRACTICE_SHAPE = {"prompt": (str, True), "starter_code": (str, False), "sample_answer": (str, True),
                  "checklist": (list, True), "approved": (bool, False)}
NONEMPTY = {"slug", "title", "name", "tagline", "summary", "url", "prompt", "body", "brief", "sample_answer"}


class CurriculumError(Exception):
    def __init__(self, errors):
        super().__init__("\n".join(errors))
        self.errors = errors


# ---------- Loading ----------

def load(directory=CURRICULUM_DIR):
    """Read the files into one dict: {"version", "paths", "tracks": [...]}, tracks in file-name order."""
    directory = FilePath(directory)
    root = json.loads((directory / "curriculum.json").read_text(encoding="utf-8"))
    tracks = [json.loads(f.read_text(encoding="utf-8")) for f in sorted((directory / "tracks").glob("*.json"))]
    tracks.sort(key=lambda t: (t.get("order", 0) if isinstance(t, dict) else 0))
    return {"version": root.get("version"), "paths": root.get("paths", []), "tracks": tracks}


def checksum(directory=CURRICULUM_DIR):
    digest = hashlib.sha256()
    directory = FilePath(directory)
    for f in [directory / "curriculum.json", *sorted((directory / "tracks").glob("*.json"))]:
        digest.update(f.name.encode())
        digest.update(f.read_bytes())
    return digest.hexdigest()


# ---------- Validation ----------

def _check_shape(obj, shape, where, errors):
    if not isinstance(obj, dict):
        errors.append(f"{where}: must be an object")
        return False
    for name in obj:
        if name not in shape and name != "order":
            errors.append(f"{where}: unknown field {name!r}")
    for name, (kind, required) in shape.items():
        if name not in obj:
            if required:
                errors.append(f"{where}: missing {name!r}")
            continue
        value = obj[name]
        if kind is int and (isinstance(value, bool) or not isinstance(value, int)):
            errors.append(f"{where}.{name}: must be a whole number")
        elif kind is not int and not isinstance(value, kind):
            errors.append(f"{where}.{name}: must be a {kind.__name__}")
        elif name in NONEMPTY and not value.strip():
            errors.append(f"{where}.{name}: must not be empty")
    return True


def _strings(value, where, errors, minimum=1):
    if not isinstance(value, list) or not all(isinstance(v, str) and v.strip() for v in value):
        errors.append(f"{where}: must be a list of non-empty strings")
    elif len(value) < minimum:
        errors.append(f"{where}: needs at least {minimum}")


def _find_cycle(prereqs):
    """A topic slug on a prerequisite cycle, or None."""
    state = {}

    def visit(node):
        state[node] = "open"
        for nxt in prereqs.get(node, ()):
            if state.get(nxt) == "open" or (nxt not in state and visit(nxt)):
                return True
        state[node] = "done"
        return False

    for node in prereqs:
        if node not in state and visit(node):
            return node
    return None


def validate(data):
    """Every problem in the curriculum, as readable strings. An empty list means it's valid."""
    errors = []
    if not isinstance(data.get("version"), str) or not data["version"].strip():
        errors.append("curriculum.json: 'version' must be a non-empty string, e.g. \"2026.11.15\"")

    track_slugs, topic_slugs = set(), {}
    for t_index, track in enumerate(data.get("tracks", [])):
        where = f"track {track.get('slug', t_index) if isinstance(track, dict) else t_index}"
        if not _check_shape(track, TRACK_SHAPE, where, errors):
            continue
        slug = track.get("slug", "")
        if isinstance(slug, str) and not SLUG.match(slug):
            errors.append(f"{where}: slug must be lowercase words joined by hyphens")
        if slug in track_slugs:
            errors.append(f"{where}: another track has the same slug")
        track_slugs.add(slug)
        for i, step in enumerate(track.get("setup_steps", [])):
            if _check_shape(step, STEP_SHAPE, f"{where} setup step {i + 1}", errors) and step.get("link"):
                _check_url(step["link"], f"{where} setup step {i + 1}.link", errors)
        for i, idea in enumerate(track.get("project_ideas", [])):
            if _check_shape(idea, IDEA_SHAPE, f"{where} project {i + 1}", errors):
                _strings(idea.get("done_when"), f"{where} project {i + 1}.done_when", errors)
        topics = track.get("topics", [])
        if not isinstance(topics, list):
            continue
        own = {t.get("slug") for t in topics if isinstance(t, dict)}
        prereqs = {}
        for topic in topics:
            _validate_topic(topic, track, where, own, topic_slugs, prereqs, errors)
        if (start := _find_cycle(prereqs)) is not None:
            errors.append(f"{where}: prerequisites go in a circle through {start!r}")
        if track.get("is_active") is True:
            _validate_supported(track, where, errors)

    path_slugs = set()
    for i, path in enumerate(data.get("paths", [])):
        where = f"path {path.get('slug', i) if isinstance(path, dict) else i}"
        if not _check_shape(path, PATH_SHAPE, where, errors):
            continue
        if path.get("slug") in path_slugs:
            errors.append(f"{where}: another path has the same slug")
        path_slugs.add(path.get("slug"))
        tracks = path.get("tracks", [])
        if not tracks:
            errors.append(f"{where}: needs at least one track")
        for slug in tracks if isinstance(tracks, list) else []:
            if slug not in track_slugs:
                errors.append(f"{where}: no track {slug!r}")
        if len(set(tracks)) != len(tracks):
            errors.append(f"{where}: lists a track twice")
    return errors


def _check_url(url, where, errors):
    if not isinstance(url, str) or not url.startswith("https://"):
        errors.append(f"{where}: must be an https:// link")


def _validate_topic(topic, track, where, own, topic_slugs, prereqs, errors):
    t_where = f"{where} topic {topic.get('slug', '?') if isinstance(topic, dict) else '?'}"
    if not _check_shape(topic, TOPIC_SHAPE, t_where, errors):
        return
    slug = topic.get("slug", "")
    if isinstance(slug, str) and not SLUG.match(slug):
        errors.append(f"{t_where}: slug must be lowercase words joined by hyphens")
    if slug in topic_slugs:
        errors.append(f"{t_where}: slug also used in track {topic_slugs[slug]!r}; topic slugs are unique across tracks")
    topic_slugs[slug] = track.get("slug")
    minutes = topic.get("estimated_minutes")
    if isinstance(minutes, int) and not 5 <= minutes <= 600:
        errors.append(f"{t_where}.estimated_minutes: must be between 5 and 600")
    needs = topic.get("prerequisites", [])
    if isinstance(needs, list):
        for need in needs:
            if need == slug:
                errors.append(f"{t_where}: can't be its own prerequisite")
            elif need not in own:
                errors.append(f"{t_where}: prerequisite {need!r} isn't a topic in this track")
        prereqs[slug] = [n for n in needs if n in own and n != slug]
    terms = topic.get("key_terms", [])
    if not isinstance(terms, list) or len(terms) > 3 or not all(
        isinstance(k, dict) and set(k) == {"term", "definition"} and all(isinstance(v, str) and v.strip() for v in k.values())
        for k in terms
    ):
        errors.append(f"{t_where}.key_terms: up to 3, each {{\"term\": ..., \"definition\": ...}}")
    for i, resource in enumerate(topic.get("resources", [])):
        r_where = f"{t_where} resource {i + 1}"
        if _check_shape(resource, RESOURCE_SHAPE, r_where, errors):
            _check_url(resource.get("url"), f"{r_where}.url", errors)
            if resource.get("kind") not in RESOURCE_KINDS:
                errors.append(f"{r_where}.kind: one of {', '.join(sorted(RESOURCE_KINDS))}")
    _strings(topic.get("tips", []), f"{t_where}.tips", errors, minimum=0)
    for i, q in enumerate(topic.get("skill_questions", [])):
        q_where = f"{t_where} skill question {i + 1}"
        if _check_shape(q, QUESTION_SHAPE, q_where, errors):
            _strings(q.get("choices"), f"{q_where}.choices", errors, minimum=2)
            index, choices = q.get("correct_index"), q.get("choices")
            if isinstance(index, int) and isinstance(choices, list) and not 0 <= index < len(choices):
                errors.append(f"{q_where}.correct_index: must point at a choice (0 to {len(choices) - 1})")
    for i, q in enumerate(topic.get("quiz_items", [])):
        q_where = f"{t_where} quiz item {i + 1}"
        if _check_shape(q, QUIZ_SHAPE, q_where, errors):
            _strings(q.get("accepted_answers"), f"{q_where}.accepted_answers", errors)
            if "___" not in q.get("prompt", ""):
                errors.append(f"{q_where}.prompt: mark the blank with ___")
    for i, task in enumerate(topic.get("practice_tasks", [])):
        p_where = f"{t_where} practice task {i + 1}"
        if _check_shape(task, PRACTICE_SHAPE, p_where, errors):
            _strings(task.get("checklist"), f"{p_where}.checklist", errors)


def _validate_supported(track, where, errors):
    """What a track needs before learners see it: the bar for a "supported" language."""
    if not any(i.get("is_active", True) for i in track.get("project_ideas", []) if isinstance(i, dict)):
        errors.append(f"{where}: an active track needs a project idea with \"done when\" checks")
    topics = [t for t in track.get("topics", []) if isinstance(t, dict)]
    if not topics:
        errors.append(f"{where}: an active track needs topics")
    for topic in topics:
        t_where = f"{where} topic {topic.get('slug')}"
        if not any(r.get("is_active", True) for r in topic.get("resources", []) if isinstance(r, dict)):
            errors.append(f"{t_where}: an active track's topics need at least one active resource")
        if not topic.get("quiz_items"):
            errors.append(f"{t_where}: an active track's topics need a checkpoint (quiz items)")


def load_valid(directory=CURRICULUM_DIR):
    data = load(directory)
    errors = validate(data)
    if errors:
        raise CurriculumError(errors)
    return data


# ---------- Export: database to files ----------

def _clean(d, defaults):
    """Leave out fields that hold their default, so files stay short."""
    return {k: v for k, v in d.items() if k not in defaults or v != defaults[k]}


def export_track(track):
    topics = []
    for topic in track.topics.order_by("order", "title").prefetch_related(
        "prerequisites", "resources", "tips", "skill_questions", "quiz_items", "practice_tasks"
    ):
        topics.append(_clean({
            "slug": topic.slug, "title": topic.title, "summary": topic.summary,
            "why_it_matters": topic.why_it_matters, "key_terms": topic.key_terms,
            "explanation": topic.explanation, "example": topic.example, "example_output": topic.example_output,
            "intro_approved": topic.intro_approved, "estimated_minutes": topic.estimated_minutes,
            "prerequisites": [p.slug for p in topic.prerequisites.order_by("order", "title")],
            "resources": [_clean({
                "title": r.title, "url": r.url, "kind": r.kind, "estimated_minutes": r.estimated_minutes,
                "is_active": r.is_active,
            }, {"estimated_minutes": 15, "is_active": True}) for r in topic.resources.order_by("order", "pk")],
            "tips": [t.text for t in topic.tips.order_by("order", "pk")],
            "skill_questions": [_clean({
                "prompt": q.prompt, "code_snippet": q.code_snippet, "choices": q.choices,
                "correct_index": q.correct_index,
            }, {"code_snippet": ""}) for q in topic.skill_questions.order_by("order", "pk")],
            "quiz_items": [_clean({
                "prompt": q.prompt, "accepted_answers": q.accepted_answers, "hint": q.hint,
                "explanation": q.explanation, "case_sensitive": q.case_sensitive,
            }, {"hint": "", "explanation": "", "case_sensitive": False}) for q in topic.quiz_items.order_by("pk")],
            "practice_tasks": [_clean({
                "prompt": p.prompt, "starter_code": p.starter_code, "sample_answer": p.sample_answer,
                "checklist": p.checklist, "approved": p.approved,
            }, {"starter_code": "", "approved": False}) for p in topic.practice_tasks.order_by("order", "pk")],
        }, {"why_it_matters": "", "key_terms": [], "explanation": "", "example": "", "example_output": "",
            "intro_approved": False, "prerequisites": [], "tips": [], "skill_questions": [], "quiz_items": [],
            "practice_tasks": []}))
    return _clean({
        "slug": track.slug, "name": track.name, "order": track.order, "description": track.description,
        "is_active": track.is_active, "setup_check": track.setup_check,
        "setup_steps": [_clean({"title": s.title, "body": s.body, "link": s.link}, {"link": ""})
                        for s in track.setup_steps.order_by("order", "pk")],
        "project_ideas": [_clean({"title": i.title, "brief": i.brief, "done_when": i.done_when, "is_active": i.is_active},
                                 {"is_active": True}) for i in track.project_ideas.order_by("order", "pk")],
        "topics": topics,
    }, {"description": "", "setup_check": "", "setup_steps": [], "project_ideas": []})


def export_paths():
    return [_clean({
        "slug": p.slug, "title": p.title, "tagline": p.tagline, "is_active": p.is_active,
        "language_reason": p.language_reason, "tracks": [t.slug for t in p.ordered_tracks()],
    }, {"is_active": True, "language_reason": ""}) for p in Path.objects.prefetch_related("path_tracks__track")]


def dumps(obj):
    return json.dumps(obj, indent=2, ensure_ascii=False) + "\n"


def export(directory=CURRICULUM_DIR, version=None):
    """Write the database's curriculum to files. Keeps the current version unless a new one is given."""
    directory = FilePath(directory)
    (directory / "tracks").mkdir(parents=True, exist_ok=True)
    root_file = directory / "curriculum.json"
    if version is None and root_file.exists():
        version = json.loads(root_file.read_text(encoding="utf-8")).get("version")
    root_file.write_text(dumps({"version": version or "unversioned", "paths": export_paths()}), encoding="utf-8")
    written = []
    for track in Track.objects.all():
        f = directory / "tracks" / f"{track.slug}.json"
        f.write_text(dumps(export_track(track)), encoding="utf-8")
        written.append(f)
    return written


# ---------- Import: files to database ----------

@dataclass
class ImportReport:
    created: dict = field(default_factory=dict)
    updated: dict = field(default_factory=dict)
    removed: dict = field(default_factory=dict)
    kept: list = field(default_factory=list)  # Rows not in the files that were left alone, and why.

    def count(self, bucket, kind, n=1):
        getattr(self, bucket)[kind] = getattr(self, bucket).get(kind, 0) + n

    @property
    def changed(self):
        return bool(self.created or self.updated or self.removed)

    def as_dict(self):
        return {"created": self.created, "updated": self.updated, "removed": self.removed, "kept": self.kept}


def _save(obj, values, report, kind):
    """Set fields and save only when something changed."""
    changed = obj.pk is None or any(getattr(obj, k) != v for k, v in values.items())
    if not changed:
        return obj
    created = obj.pk is None
    for k, v in values.items():
        setattr(obj, k, v)
    obj.full_clean(validate_unique=False, validate_constraints=False)
    obj.save()
    report.count("created" if created else "updated", kind)
    return obj


def _sync_children(report, kind, existing, wanted, make, prune):
    """Match child rows to the file by position: update in place, add new ones, then prune extras.

    `make(obj_or_None, values, order)` saves one; `prune(obj)` returns a reason it was kept, or None
    after removing it.
    """
    existing = list(existing)
    for i, values in enumerate(wanted, 1):
        make(existing[i - 1] if i <= len(existing) else None, values, i)
    for obj in existing[len(wanted):]:
        reason = prune(obj)
        if reason:
            report.kept.append(f"{kind} {obj}: {reason}")
        else:
            report.count("removed", kind)


def _delete_unless(obj, answered, what):
    if answered:
        return f"not in the files, but learners have {what}, so it was kept. Delete it in admin if you're sure"
    obj.delete()
    return None


@transaction.atomic
def import_curriculum(data, version, digest):
    """Make the database match the files. Returns an ImportReport. Call with validated data."""
    report = ImportReport()
    tracks = {}
    for order, t in enumerate(data["tracks"], 1):
        track = Track.objects.filter(slug=t["slug"]).first() or Track(slug=t["slug"])
        tracks[t["slug"]] = _save(track, {
            "name": t["name"], "description": t.get("description", ""), "order": t.get("order", order),
            "is_active": t["is_active"], "setup_check": t.get("setup_check", ""),
        }, report, "track")
        _import_track(tracks[t["slug"]], t, report)

    for order, p in enumerate(data["paths"], 1):
        path = Path.objects.filter(slug=p["slug"]).first() or Path(slug=p["slug"])
        path = _save(path, {
            "title": p["title"], "tagline": p["tagline"], "order": order, "is_active": p.get("is_active", True),
            "language_reason": p.get("language_reason", ""),
        }, report, "path")
        wanted = [tracks[s] for s in p["tracks"]]
        current = [pt.track for pt in path.path_tracks.select_related("track").order_by("order", "pk")]
        if current != wanted:
            path.path_tracks.all().delete()
            PathTrack.objects.bulk_create(PathTrack(path=path, track=t, order=i) for i, t in enumerate(wanted, 1))
            report.count("updated", "path tracks")

    in_files = {t["slug"] for tr in data["tracks"] for t in tr["topics"]}
    for topic in Topic.objects.filter(track__slug__in=tracks).exclude(slug__in=in_files):
        report.kept.append(f"topic {topic.slug}: not in the files; kept so plans that have it still work")

    if report.changed or CurriculumRelease.current_version() != version:
        CurriculumRelease.objects.create(version=version, checksum=digest, summary=report.as_dict())
    return report


def _import_track(track, t, report):
    def make_step(obj, v, order):
        _save(obj or SetupStep(track=track), {"order": order, "title": v["title"], "body": v["body"],
                                              "link": v.get("link", "")}, report, "setup step")

    def make_idea(obj, v, order):
        _save(obj or ProjectIdea(track=track), {"order": order, "title": v["title"], "brief": v["brief"],
                                                "done_when": v["done_when"], "is_active": v.get("is_active", True)},
              report, "project idea")

    def retire_idea(obj):
        if obj.is_active:
            obj.is_active = False
            obj.save(update_fields=["is_active"])
            return None
        return "already inactive"

    _sync_children(report, "setup step", track.setup_steps.order_by("order", "pk"), t.get("setup_steps", []),
                   make_step, lambda o: o.delete())
    _sync_children(report, "project idea", track.project_ideas.order_by("order", "pk"), t.get("project_ideas", []),
                   make_idea, retire_idea)

    topics = {}
    for order, v in enumerate(t["topics"], 1):
        topic = Topic.objects.filter(slug=v["slug"]).first() or Topic(slug=v["slug"])
        topics[v["slug"]] = _save(topic, {
            "track": track, "title": v["title"], "summary": v["summary"], "order": order,
            "why_it_matters": v.get("why_it_matters", ""), "key_terms": v.get("key_terms", []),
            "explanation": v.get("explanation", ""), "example": v.get("example", ""),
            "example_output": v.get("example_output", ""), "intro_approved": v.get("intro_approved", False),
            "estimated_minutes": v["estimated_minutes"],
        }, report, "topic")
    for v in t["topics"]:
        topic = topics[v["slug"]]
        wanted = {topics[s].pk for s in v.get("prerequisites", [])}
        if set(topic.prerequisites.values_list("pk", flat=True)) != wanted:
            topic.prerequisites.set(wanted)
            report.count("updated", "prerequisites")
        _import_topic_children(topic, v, report)


def _import_topic_children(topic, v, report):
    def make_resource(obj, r, order):
        values = {"order": order, "title": r["title"], "url": r["url"], "kind": r["kind"],
                  "estimated_minutes": r.get("estimated_minutes", 15), "is_active": r.get("is_active", True)}
        if obj is not None and obj.url != r["url"]:
            # A new link: the old link check result doesn't apply to it.
            values.update(link_status="", link_note="", failed_checks=0, last_checked=None)
        _save(obj or Resource(topic=topic), values, report, "resource")

    def retire_resource(obj):
        if obj.is_active:
            obj.is_active = False
            obj.save(update_fields=["is_active"])
            return None
        return "already inactive"

    def make_tip(obj, text, order):
        _save(obj or Tip(topic=topic), {"order": order, "text": text}, report, "tip")

    def make_question(obj, q, order):
        _save(obj or SkillQuestion(topic=topic), {
            "order": order, "prompt": q["prompt"], "code_snippet": q.get("code_snippet", ""),
            "choices": q["choices"], "correct_index": q["correct_index"],
        }, report, "skill question")

    def make_quiz(obj, q, order):
        _save(obj or QuizItem(topic=topic), {
            "prompt": q["prompt"], "accepted_answers": q["accepted_answers"], "hint": q.get("hint", ""),
            "explanation": q.get("explanation", ""), "case_sensitive": q.get("case_sensitive", False),
        }, report, "quiz item")

    def make_task(obj, p, order):
        _save(obj or PracticeTask(topic=topic), {
            "order": order, "prompt": p["prompt"], "starter_code": p.get("starter_code", ""),
            "sample_answer": p["sample_answer"], "checklist": p["checklist"], "approved": p.get("approved", False),
        }, report, "practice task")

    from diagnose.models import SkillAnswer
    from learning.models import PracticeSubmission, QuizAttempt

    _sync_children(report, "resource", topic.resources.order_by("order", "pk"), v["resources"],
                   make_resource, retire_resource)
    _sync_children(report, "tip", topic.tips.order_by("order", "pk"), v.get("tips", []),
                   make_tip, lambda o: o.delete())
    _sync_children(report, "skill question", topic.skill_questions.order_by("order", "pk"),
                   v.get("skill_questions", []), make_question,
                   lambda o: _delete_unless(o, SkillAnswer.objects.filter(question=o).exists(), "answered it"))
    _sync_children(report, "quiz item", topic.quiz_items.order_by("pk"), v.get("quiz_items", []), make_quiz,
                   lambda o: _delete_unless(o, QuizAttempt.objects.filter(quiz_item=o).exists(), "answered it"))
    _sync_children(report, "practice task", topic.practice_tasks.order_by("order", "pk"),
                   v.get("practice_tasks", []), make_task,
                   lambda o: _delete_unless(o, PracticeSubmission.objects.filter(task=o).exists(), "sent answers"))


def all_resource_urls(data):
    """(where, url) for every active resource in active and inactive tracks, for the link check."""
    for track in data["tracks"]:
        for topic in track["topics"]:
            for r in topic["resources"]:
                if r.get("is_active", True):
                    yield f"{track['slug']} / {topic['slug']} / {r['title']}", r["url"]
