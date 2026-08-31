import json
from datetime import timedelta

from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from dashboard.models import (
    ClaimChallenge,
    ClaimSession,
    ClaimThrottle,
    Player,
    PlayerClaimData,
)


@override_settings(
    SITE_AUTH_REQUIRED=False,
    PLAYER_CLAIMS_ENABLED=True,
    PLAYER_HASH_SECRET="test-player-secret",
)
class PlayerClaimTests(TestCase):
    player_id = "a" * 24

    def setUp(self):
        now = timezone.now()
        Player.objects.create(
            public_id=self.player_id,
            name="Explorer",
            first_seen=now,
            last_seen=now,
        )
        PlayerClaimData.objects.create(
            public_id=self.player_id,
            snapshot_at=now,
            payload={
                "player_name": "Explorer",
                "inventory": {
                    "common": [
                        {"slot": 0, "item_id": "Stone", "count": 1},
                        {"slot": 1, "item_id": "Wood", "count": 2},
                        {"slot": 2, "item_id": "Berry", "count": 3},
                    ],
                    "weapons": [],
                    "armor": [],
                    "food": [],
                    "drop_slot": [],
                    "essential": [],
                },
                "party": [],
                "progress": {
                    "fast_travel": [],
                    "areas": [],
                    "notes": [],
                    "relics": [],
                    "item_pickups": [],
                    "normal_bosses": ["81_1_grass_fboss_14"],
                    "tower_bosses": [],
                },
            },
        )

    def start(self):
        return self.client.post(
            reverse("live-map-player-claims"),
            data=json.dumps({"playerId": self.player_id}),
            content_type="application/json",
        )

    def test_claim_can_cycle_verify_and_read_private_progress(self):
        response = self.start()
        self.assertEqual(response.status_code, 201)
        challenge = response.json()
        self.assertEqual(challenge["status"], "ready")
        self.assertEqual(len(challenge["instructions"]["questions"]), 1)
        question = challenge["instructions"]["questions"][0]
        self.assertTrue(question["canCycle"])

        cycled = self.client.post(
            reverse("live-map-player-claims-cycle"),
            data=json.dumps({
                "challengeToken": challenge["challengeToken"],
                "questionId": question["id"],
            }),
            content_type="application/json",
        )
        self.assertEqual(cycled.status_code, 200)
        next_question = cycled.json()["instructions"]["questions"][0]
        self.assertNotEqual(next_question["id"], question["id"])

        expected = {
            "What was in inventory slot 1?": "Stone",
            "What was in inventory slot 2?": "Wood",
            "What was in inventory slot 3?": "Berry",
        }[next_question["prompt"]]
        answer = next_question["options"].index(expected)
        verified = self.client.post(
            reverse("live-map-player-claims-verify"),
            data=json.dumps({
                "challengeToken": challenge["challengeToken"],
                "answers": [{"questionId": next_question["id"], "option": answer}],
            }),
            content_type="application/json",
        )
        self.assertEqual(verified.status_code, 200)
        session_token = verified.json()["sessionToken"]
        self.assertTrue(ClaimSession.objects.exists())
        self.assertFalse(ClaimChallenge.objects.exists())

        progress = self.client.get(
            reverse("live-map-claim-progress"),
            HTTP_AUTHORIZATION=f"Bearer {session_token}",
        )
        self.assertEqual(progress.status_code, 200)
        payload = progress.json()
        self.assertEqual(len(payload["domains"]), 8)
        self.assertEqual(payload["catalogueVersion"], "66fc7c1008062208ee8e49a4e3e0a01e0b2eaa57c78b41ba8d00e18deb0e1fe4")
        self.assertEqual(payload["domains"][0]["id"], "alpha-pals")

    def test_wrong_answer_consumes_challenge(self):
        response = self.start()
        challenge = response.json()
        question = challenge["instructions"]["questions"][0]
        expected = {
            "What was in inventory slot 1?": "Stone",
            "What was in inventory slot 2?": "Wood",
            "What was in inventory slot 3?": "Berry",
        }[question["prompt"]]
        wrong_option = (question["options"].index(expected) + 1) % len(question["options"])
        wrong = self.client.post(
            reverse("live-map-player-claims-verify"),
            data=json.dumps({
                "challengeToken": challenge["challengeToken"],
                "answers": [{"questionId": question["id"], "option": wrong_option}],
            }),
            content_type="application/json",
        )
        self.assertEqual(wrong.status_code, 401)
        self.assertEqual(wrong.json(), {"error": "verification_failed"})
        self.assertFalse(ClaimChallenge.objects.exists())

    def test_verify_requires_exactly_one_answer(self):
        response = self.start()
        challenge = response.json()

        invalid = self.client.post(
            reverse("live-map-player-claims-verify"),
            data=json.dumps({
                "challengeToken": challenge["challengeToken"],
                "answers": [],
            }),
            content_type="application/json",
        )

        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(invalid.json(), {"error": "invalid_request"})
        self.assertTrue(ClaimChallenge.objects.exists())

    def test_expired_session_is_rejected(self):
        now = timezone.now()
        token = "A" * 43
        ClaimSession.objects.create(
            bearer_hash="0" * 64,
            subject="subject",
            public_player_id=self.player_id,
            idle_expires_at=now - timedelta(seconds=1),
            absolute_expires_at=now + timedelta(days=1),
        )
        response = self.client.get(
            reverse("live-map-claim-progress"),
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json(), {"error": "authentication_required"})

    def test_claim_is_unavailable_for_missing_data(self):
        PlayerClaimData.objects.all().delete()
        response = self.start()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"error": "claim_unavailable"})

    def test_expired_throttle_rows_are_pruned(self):
        ClaimThrottle.objects.create(
            key="old",
            window_started_at=timezone.now() - timedelta(hours=2),
            attempts=1,
        )

        response = self.start()

        self.assertEqual(response.status_code, 201)
        self.assertFalse(ClaimThrottle.objects.filter(key="old").exists())


@override_settings(SITE_AUTH_REQUIRED=False)
class PlayerClaimOpenAPITests(SimpleTestCase):
    def test_claim_operations_and_security_schemes_are_documented(self):
        response = self.client.get(reverse("openapi-schema"))

        self.assertEqual(response.status_code, 200)
        document = response.json()
        paths = document["paths"]
        self.assertEqual(
            paths["/api/v1/live-map/player-claims"]["post"]["responses"]["201"]["$ref"],
            "#/components/responses/ClaimReady",
        )
        self.assertEqual(
            paths["/api/v1/live-map/player-claims/questions/cycle"]["post"]["responses"]["200"]["$ref"],
            "#/components/responses/ClaimCycled",
        )
        self.assertEqual(
            paths["/api/v1/live-map/me/progress"]["get"]["security"],
            [{"cookieAuth": [], "claimBearerAuth": []}],
        )
        self.assertIn("claimBearerAuth", document["components"]["securitySchemes"])
        self.assertIn("ClaimProgressResponse", document["components"]["schemas"])
