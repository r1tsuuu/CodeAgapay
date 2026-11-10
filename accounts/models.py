import uuid

from django.conf import settings
from django.db import models


class LearnerProfile(models.Model):
    """Created on first visit to `home`, so everything but the user starts blank."""

    class Experience(models.TextChoices):
        NONE = "none", "I've never coded"
        A_LITTLE = "a_little", "I've tried a little"
        COMFORTABLE = "comfortable", "I'm fairly comfortable"

    class Device(models.TextChoices):
        WINDOWS = "windows", "A Windows computer"
        MAC = "mac", "A Mac"
        LINUX = "linux", "A Linux computer"
        CHROMEBOOK = "chromebook", "A Chromebook"
        PHONE = "phone", "A phone or tablet"

    class HintStyle(models.TextChoices):
        THINK = "think", "A hint that makes me think"
        EXPLAIN = "explain", "A clear explanation"
        EXAMPLE = "example", "An example I can learn from"

    class Avatar(models.TextChoices):
        """Profile icons from the Figma "Custom Profile Page", in static/img/avatars/. Blank shows the first letter."""

        AVATAR_1 = "avatar-1", "Glasses and a moustache"
        AVATAR_2 = "avatar-2", "Long yellow hair"
        AVATAR_3 = "avatar-3", "Short black hair"
        AVATAR_4 = "avatar-4", "Long brown hair"
        AVATAR_5 = "avatar-5", "Hair in a bun"
        AVATAR_6 = "avatar-6", "Curly brown hair"
        AVATAR_7 = "avatar-7", "Spiky black hair"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="learner_profile"
    )
    experience = models.CharField(max_length=20, choices=Experience.choices, blank=True)
    hours_per_week = models.PositiveIntegerField(null=True, blank=True)
    goal_text = models.CharField(max_length=300, blank=True)
    track = models.ForeignKey(
        "content.Track", on_delete=models.SET_NULL, null=True, blank=True, related_name="learners"
    )
    path = models.ForeignKey(
        "content.Path", on_delete=models.SET_NULL, null=True, blank=True, related_name="learners"
    )
    target_weeks = models.PositiveIntegerField(
        null=True, blank=True, help_text="Weeks until a date they're aiming for, if any."
    )
    device = models.CharField(
        max_length=20, choices=Device.choices, blank=True,
        help_text="What they'll learn on. Setup and lessons use its shortcuts and app names. Blank: not sure.",
    )
    hint_style = models.CharField(
        max_length=20, choices=HintStyle.choices, blank=True, help_text="What helps them most when stuck."
    )
    email_reminders = models.BooleanField(default=False, help_text="Off until the learner says yes.")
    reminders_asked = models.BooleanField(
        default=False, help_text="The learner has answered the reminders question."
    )
    last_reminder_at = models.DateTimeField(null=True, blank=True)
    reminders_unanswered = models.PositiveIntegerField(
        default=0, help_text="Reminders sent since the learner was last active. Stops at a small limit."
    )
    # Stored, not signed: emails go out from a laptop, whose SECRET_KEY differs from the live site's.
    unsubscribe_key = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    setup_done = models.ManyToManyField(
        "content.Track", blank=True, related_name="+", help_text="Tracks whose setup the learner finished."
    )
    onboarded = models.BooleanField(default=False)
    avatar = models.CharField(max_length=20, choices=Avatar.choices, blank=True, help_text="Blank: the first letter of their name.")
    school = models.CharField("school or organisation", max_length=120, blank=True)
    role = models.CharField(max_length=60, blank=True, help_text='What they do, e.g. "student". Optional.')
    ai_plans_early = models.BooleanField(
        "gets AI plans early", default=False,
        help_text="Gets AI-written plans and lessons while AI_PLANS is still off for everyone (gradual rollout).",
    )

    def __str__(self):
        return f"Profile of {self.user}"

    @property
    def avatar_file(self):
        """The chosen icon's file name, or "" when none is chosen or it's no longer offered."""
        return self.avatar if self.avatar in self.Avatar.values else ""

    def gets_ai_plans(self):
        """AI-written plans for this learner: everyone's on (AI_PLANS), or they're in the early group."""
        return settings.AI_PLANS or self.ai_plans_early


def get_profile(user):
    profile, _ = LearnerProfile.objects.get_or_create(user=user)
    return profile
