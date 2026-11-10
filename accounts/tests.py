import uuid

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from content.models import Topic, Track
from learning.models import PlanItem
from learning.planner import build_plan, set_item_status

from .models import LearnerProfile, get_profile


class LoginRequiredTests(TestCase):
    def test_anonymous_home_redirects_to_login(self):
        response = self.client.get(reverse("home"))
        self.assertRedirects(response, f"{reverse('account_login')}?next=/", fetch_redirect_response=False)

    def test_login_page_offers_google_only(self):
        response = self.client.get(reverse("account_login"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "/accounts/google/login/")
        self.assertNotContains(response, 'type="password"')


class HomeTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("ana", "ana@example.com", first_name="Ana")
        self.client.force_login(self.user)

    def test_first_visit_creates_profile_and_goes_to_welcome(self):
        response = self.client.get(reverse("home"))
        self.assertRedirects(response, reverse("welcome"))
        self.assertTrue(LearnerProfile.objects.filter(user=self.user, onboarded=False).exists())

    def test_welcome_greets_learner(self):
        self.assertContains(self.client.get(reverse("welcome")), "Hi, Ana!")

    def test_logout_page_uses_site_layout(self):
        response = self.client.get(reverse("account_logout"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "navbar")


class ProfileTests(TestCase):
    def setUp(self):
        self.track = Track.objects.create(name="Python", slug="python")
        for i in (1, 2, 3):
            Topic.objects.create(track=self.track, title=f"T{i}", slug=f"t{i}", order=i, estimated_minutes=60)
        self.user = get_user_model().objects.create_user("ana", "ana@example.com", first_name="Ana", last_name="Cruz")
        self.profile = get_profile(self.user)
        self.profile.track = self.track
        self.profile.onboarded = True
        self.profile.hours_per_week = 1
        self.profile.goal_text = "Automate my org's attendance"
        self.profile.save()
        self.client.force_login(self.user)
        self.url = reverse("profile")
        self.setup_url = reverse("profile_setup")

    def save(self, **changes):
        data = {"goal_text": self.profile.goal_text, "hours_per_week": 1, "experience": "none", "device": "windows",
                "hint_style": "think", "email_reminders": "on", **changes}
        return self.client.post(self.setup_url, {k: v for k, v in data.items() if v is not None})

    def test_needs_a_login(self):
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 302)

    def test_not_onboarded_goes_to_welcome(self):
        self.profile.onboarded = False
        self.profile.save()
        self.assertRedirects(self.client.get(self.url), reverse("welcome"))

    def test_shows_who_they_are_and_their_setup(self):
        page = self.client.get(self.url)
        self.assertContains(page, "<h1>Ana Cruz</h1>", html=True)
        self.assertContains(page, "ana@example.com")
        self.assertContains(page, "Automate my org&#x27;s attendance")
        self.assertContains(page, 'value="1"')
        self.assertContains(page, "You don't have a plan yet.")

    def test_account_menu_links_here(self):
        self.assertContains(self.client.get(reverse("welcome")), f'href="{self.url}">My profile')

    def test_saves_learning_setup(self):
        response = self.save(hint_style="example", device="mac", experience="a_little", goal_text="Make a game")
        self.assertRedirects(response, self.url + "#learning-setup", fetch_redirect_response=False)
        self.profile.refresh_from_db()
        self.assertEqual(
            (self.profile.hint_style, self.profile.device, self.profile.experience, self.profile.goal_text),
            ("example", "mac", "a_little", "Make a game"),
        )
        self.assertTrue(self.profile.email_reminders)
        self.save(email_reminders=None)
        self.profile.refresh_from_db()
        self.assertFalse(self.profile.email_reminders)

    def test_saving_counts_as_answering_the_reminders_question(self):
        self.save(email_reminders=None)
        self.profile.refresh_from_db()
        self.assertTrue(self.profile.reminders_asked)

    def test_changing_hours_respaces_the_plan_and_keeps_progress(self):
        plan = build_plan(self.profile)
        first = plan.items.order_by("order").first()
        set_item_status(first, PlanItem.Status.DONE)
        self.save(hours_per_week=3)
        self.assertEqual(set(plan.items.values_list("week", flat=True)), {1})
        first.refresh_from_db()
        self.assertEqual(first.status, PlanItem.Status.DONE)

    def test_works_without_a_plan(self):
        self.assertRedirects(self.save(hours_per_week=5), self.url + "#learning-setup", fetch_redirect_response=False)

    def test_rejects_impossible_hours_and_opens_the_form(self):
        response = self.save(hours_per_week=0)
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, '<details class="profile-edit" open>', status_code=400)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.hours_per_week, 1)

    def test_shows_progress_and_the_next_topic(self):
        plan = build_plan(self.profile)
        set_item_status(plan.items.order_by("order").first(), PlanItem.Status.DONE)
        page = self.client.get(self.url)
        self.assertContains(page, "1 topic done out of 3")
        self.assertContains(page, "33%")
        self.assertContains(page, "Continue “T2”")
        self.assertContains(page, '<span class="status status-done">completed</span>', html=True)
        self.assertContains(page, '<span class="status status-todo">not started</span>', html=True)

    def test_saves_details(self):
        self.client.post(reverse("profile_details"), {"first_name": "Maria", "last_name": "Santos",
                                                      "school": "Ateneo", "role": "student"})
        self.user.refresh_from_db()
        self.profile.refresh_from_db()
        self.assertEqual((self.user.get_full_name(), self.profile.school, self.profile.role),
                         ("Maria Santos", "Ateneo", "student"))
        self.assertContains(self.client.get(self.url), "<dd>Ateneo</dd>", html=True)

    def test_details_need_a_first_name(self):
        response = self.client.post(reverse("profile_details"), {"first_name": " ", "last_name": "", "school": "", "role": ""})
        self.assertEqual(response.status_code, 400)
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, "Ana")

    def test_icon_shows_in_the_menu(self):
        self.client.post(reverse("profile_icon"), {"avatar": "star-pink"})
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.avatar, "star-pink")
        self.assertContains(self.client.get(reverse("welcome")), "img/mascots/star-pink.svg")
        self.client.post(reverse("profile_icon"), {"avatar": ""})  # back to the first letter
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.avatar, "")

    def test_unknown_icon_is_rejected(self):
        response = self.client.post(reverse("profile_icon"), {"avatar": "../../secret"})
        self.assertEqual(response.status_code, 400)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.avatar, "")

    def test_old_settings_link_goes_to_the_profile(self):
        old = reverse("account_settings")
        self.assertRedirects(self.client.get(old), self.url + "#learning-setup", fetch_redirect_response=False)
        self.client.post(old, {"hours_per_week": 4, "hint_style": "example"})
        self.profile.refresh_from_db()
        self.assertEqual((self.profile.hours_per_week, self.profile.hint_style), (4, "example"))


class DeleteAccountTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("ana", "ana@example.com")
        self.profile = get_profile(self.user)
        self.client.force_login(self.user)
        self.url = reverse("delete_account")

    def test_asks_first(self):
        self.assertContains(self.client.get(self.url), "This can't be undone.")
        self.assertTrue(get_user_model().objects.filter(pk=self.user.pk).exists())

    def test_needs_the_word_delete(self):
        self.client.post(self.url, {"confirm": "yes"})
        self.assertTrue(get_user_model().objects.filter(pk=self.user.pk).exists())

    def test_deletes_the_login_and_everything_linked(self):
        response = self.client.post(self.url, {"confirm": "delete"})
        self.assertRedirects(response, reverse("account_login"), fetch_redirect_response=False)
        self.assertFalse(get_user_model().objects.filter(pk=self.user.pk).exists())
        self.assertFalse(LearnerProfile.objects.filter(pk=self.profile.pk).exists())
        self.assertEqual(self.client.get(reverse("home")).status_code, 302)  # logged out


class ReminderChoiceTests(TestCase):
    def setUp(self):
        self.track = Track.objects.create(name="Python", slug="python")
        Topic.objects.create(track=self.track, title="T1", slug="t1", order=1)
        self.user = get_user_model().objects.create_user("ana", "ana@example.com")
        self.profile = get_profile(self.user)
        self.profile.track = self.track
        self.profile.onboarded = True
        self.profile.save()
        build_plan(self.profile)
        self.client.force_login(self.user)

    def choose(self, choice):
        response = self.client.post(reverse("reminder_choice"), {"choice": choice})
        self.profile.refresh_from_db()
        return response

    def test_reminders_stay_off_until_the_learner_says_yes(self):
        self.assertFalse(self.profile.email_reminders)

    def test_plan_page_asks_until_answered(self):
        self.assertContains(self.client.get(reverse("plan")), "Yes, remind me")
        self.choose("no")
        self.assertNotContains(self.client.get(reverse("plan")), "Yes, remind me")

    def test_yes_turns_reminders_on(self):
        self.assertRedirects(self.choose("yes"), reverse("plan"))
        self.assertTrue(self.profile.email_reminders)
        self.assertTrue(self.profile.reminders_asked)

    def test_no_keeps_them_off(self):
        self.choose("no")
        self.assertFalse(self.profile.email_reminders)
        self.assertTrue(self.profile.reminders_asked)

    def test_anything_else_is_not_a_yes(self):
        self.choose("")
        self.assertFalse(self.profile.email_reminders)

    def test_opening_the_link_changes_nothing(self):
        self.assertEqual(self.client.get(reverse("reminder_choice")).status_code, 405)

    def test_not_asked_without_an_email_to_send_to(self):
        self.user.email = ""
        self.user.save()
        self.assertNotContains(self.client.get(reverse("plan")), "Yes, remind me")


class UnsubscribeTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("ana", "ana@example.com")
        self.profile = get_profile(self.user)
        self.profile.email_reminders = True
        self.profile.save()
        self.url = reverse("unsubscribe", args=[self.profile.unsubscribe_key])

    def reminders_on(self):
        self.profile.refresh_from_db()
        return self.profile.email_reminders

    def test_opening_the_link_changes_nothing(self):
        # Mail scanners open links, so a GET must never unsubscribe anyone.
        response = self.client.get(self.url)
        self.assertContains(response, "Stop reminder emails?")
        self.assertTrue(self.reminders_on())

    def test_post_turns_reminders_off_without_a_login(self):
        response = self.client.post(self.url)
        self.assertContains(response, "Reminders are off")
        self.assertFalse(self.reminders_on())

    def test_one_click_post_passes_csrf_checks(self):
        client = Client(enforce_csrf_checks=True)
        self.assertEqual(client.post(self.url, {"List-Unsubscribe": "One-Click"}).status_code, 200)
        self.assertFalse(self.reminders_on())

    def test_already_off_shows_done(self):
        self.client.post(self.url)
        self.assertContains(self.client.get(self.url), "Reminders are off")

    def test_unknown_key_is_rejected(self):
        response = self.client.post(reverse("unsubscribe", args=[uuid.uuid4()]))
        self.assertEqual(response.status_code, 404)
        self.assertTrue(self.reminders_on())

    def test_each_learner_has_their_own_key(self):
        other = get_profile(get_user_model().objects.create_user("ben", "ben@example.com"))
        other.email_reminders = True
        other.save()
        self.assertNotEqual(self.profile.unsubscribe_key, other.unsubscribe_key)
        self.client.post(self.url)
        other.refresh_from_db()
        self.assertTrue(other.email_reminders)
