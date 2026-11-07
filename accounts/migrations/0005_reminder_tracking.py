import uuid

from django.db import migrations, models


def give_each_learner_a_key(apps, schema_editor):
    LearnerProfile = apps.get_model("accounts", "LearnerProfile")
    for profile in LearnerProfile.objects.filter(unsubscribe_key__isnull=True):
        profile.unsubscribe_key = uuid.uuid4()
        profile.save(update_fields=["unsubscribe_key"])


def turn_reminders_off(apps, schema_editor):
    """The old default was on, but no learner was ever asked. They choose on the plan page."""
    apps.get_model("accounts", "LearnerProfile").objects.update(email_reminders=False)


class Migration(migrations.Migration):
    # Postgres can't alter a table in the same transaction as updating its rows here.
    atomic = False

    dependencies = [("accounts", "0004_setup_done")]

    operations = [
        migrations.AlterField(
            model_name="learnerprofile",
            name="email_reminders",
            field=models.BooleanField(default=False, help_text="Off until the learner says yes."),
        ),
        migrations.RunPython(turn_reminders_off, migrations.RunPython.noop),
        migrations.AddField(
            model_name="learnerprofile",
            name="reminders_asked",
            field=models.BooleanField(default=False, help_text="The learner has answered the reminders question."),
        ),
        migrations.AddField(
            model_name="learnerprofile",
            name="last_reminder_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="learnerprofile",
            name="reminders_unanswered",
            field=models.PositiveIntegerField(
                default=0, help_text="Reminders sent since the learner was last active. Stops at a small limit."
            ),
        ),
        # A default on AddField would give every existing learner the same key, so fill them one by one.
        migrations.AddField(
            model_name="learnerprofile",
            name="unsubscribe_key",
            field=models.UUIDField(null=True, editable=False),
        ),
        migrations.RunPython(give_each_learner_a_key, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="learnerprofile",
            name="unsubscribe_key",
            field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
        ),
    ]
