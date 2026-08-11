import unittest
from datetime import datetime, timezone

from linkedin_orphan_discovery import Activity, Connection, build_candidates, normalise_url


class OrphanDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.connection = Connection("Ada", "Lovelace", "https://linkedin.com/in/ada", "ada@example.com", "Analytical Engines", "Director of Partnerships")
        self.cutoff = datetime(2026, 1, 1, tzinfo=timezone.utc)

    def test_missing_contact_becomes_create_candidate(self):
        rows = build_candidates([self.connection], {}, [{"email": "other@example.com"}], self.cutoff)
        self.assertEqual(rows[0]["candidate_type"], "create and contact")

    def test_recent_me_activity_is_excluded(self):
        me = [{"email": "ada@example.com", "linkedin_url": "", "full_name": "Ada Lovelace", "company": "Analytical Engines", "last_activity_at": "2026-01-15T00:00:00+00:00"}]
        self.assertEqual(build_candidates([self.connection], {}, me, self.cutoff), [])

    def test_old_me_activity_becomes_reactivation(self):
        me = [{"email": "ada@example.com", "linkedin_url": "", "full_name": "Ada Lovelace", "company": "Analytical Engines", "last_activity_at": "2025-01-15T00:00:00+00:00"}]
        activity = {"https://linkedin.com/in/ada": [Activity(datetime(2025, 2, 1, tzinfo=timezone.utc), "inbound", "Can we talk?")]}
        rows = build_candidates([self.connection], activity, me, self.cutoff)
        self.assertEqual(rows[0]["candidate_type"], "reactivate")

    def test_recent_linkedin_activity_is_excluded(self):
        activity = {"https://linkedin.com/in/ada": [Activity(datetime(2026, 1, 2, tzinfo=timezone.utc), "outbound", "Hello") ]}
        self.assertEqual(build_candidates([self.connection], activity, [], self.cutoff), [])

    def test_name_company_match_requires_manual_review(self):
        me = [{"email": "", "linkedin_url": "", "full_name": "Ada Lovelace", "company": "Analytical Engines", "last_activity_at": "2025-01-01"}]
        rows = build_candidates([self.connection], {}, me, self.cutoff)
        self.assertEqual(rows[0]["candidate_type"], "manual match")

    def test_linkedin_urls_ignore_www_query_and_trailing_slash(self):
        left = normalise_url("https://www.linkedin.com/in/Ada/?trk=export")
        right = normalise_url("linkedin.com/in/ada")
        self.assertEqual(left, right)

    def test_candidate_limit_prefers_stronger_title(self):
        director = self.connection
        founder = Connection("Grace", "Hopper", "https://linkedin.com/in/grace", "", "Compilers", "Founder")
        rows = build_candidates([director, founder], {}, [], self.cutoff, max_candidates=1)
        self.assertEqual(rows[0]["full_name"], "Grace Hopper")


if __name__ == "__main__":
    unittest.main()
