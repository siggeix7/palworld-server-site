import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from tempfile import TemporaryDirectory

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase


EXPECTED_CATEGORY_COUNTS = {
    "alpha-pals": 90,
    "bosses": 9,
    "bounties": 33,
    "oil-rigs": 3,
    "dungeon-entrances": 170,
    "watchtowers": 22,
    "waypoints": 152,
    "ancient-shrine-pickups": 106,
    "effigies": 407,
    "journals": 64,
    "npc-locations": 90,
}
MAP_BOUNDS = {
    "palpagos": {
        "min_x": -1099400,
        "max_x": 349400,
        "min_y": -724400,
        "max_y": 724400,
    },
    "world-tree": {
        "min_x": 347351.5,
        "max_x": 689148.5,
        "min_y": -818197,
        "max_y": -476400,
    },
}


class MapCatalogueTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        path = (
            Path(settings.BASE_DIR)
            / "dashboard/static/dashboard/data/map-points.json"
        )
        cls.catalogue_raw = path.read_bytes()
        cls.catalogue = json.loads(cls.catalogue_raw)
        cls.points = [
            point
            for map_data in cls.catalogue["maps"].values()
            for point in map_data["points"]
        ]

    def test_schema_source_and_exact_counts(self):
        self.assertEqual(
            hashlib.sha256(self.catalogue_raw).hexdigest(),
            "c3b747e3f1686952e1a871c6785779275ef087af07caab44db260afdf5cb02e6",
        )
        self.assertEqual(self.catalogue["schema_version"], 3)
        self.assertEqual(
            self.catalogue["source"],
            {
                "repository": "https://github.com/LukeHollandDev/palworld-live-map",
                "revision": "19f3e3f8e684481bde58fef6c76845f811d57614",
                "game_version": "1.0.1.100619",
            },
        )
        self.assertEqual(self.catalogue["total_count"], 1146)
        self.assertEqual(self.catalogue["category_counts"], EXPECTED_CATEGORY_COUNTS)
        self.assertEqual(Counter(point["kind"] for point in self.points), EXPECTED_CATEGORY_COUNTS)
        self.assertEqual(len(self.points), 1146)
        self.assertEqual(
            {
                map_id: len(map_data["points"])
                for map_id, map_data in self.catalogue["maps"].items()
            },
            {"palpagos": 1064, "world-tree": 82},
        )
        for map_data in self.catalogue["maps"].values():
            self.assertEqual(map_data["point_count"], len(map_data["points"]))

    def test_points_use_only_public_fields_and_unique_hashed_ids(self):
        required_fields = {"id", "kind", "x", "y", "name"}
        allowed_fields = required_fields | {"detail", "level", "z", "rewards"}
        forbidden_fields = {
            "gameId",
            "sourceId",
            "object",
            "objectPath",
            "className",
            "instanceId",
            "stateKey",
            "iconSource",
            "sourcePackage",
            "sourceObject",
            "itemId",
            "nameSource",
        }
        ids = set()
        for point in self.points:
            self.assertTrue(required_fields <= set(point))
            self.assertTrue(set(point) <= allowed_fields)
            self.assertFalse(set(point) & forbidden_fields)
            self.assertRegex(
                point["id"], rf"^{re.escape(point['kind'])}-[0-9a-f]{{20}}$"
            )
            self.assertNotIn(point["id"], ids)
            ids.add(point["id"])
            for reward in point.get("rewards", []):
                self.assertEqual(set(reward), {"name", "count"})
                self.assertIsInstance(reward["name"], str)
                self.assertIsInstance(reward["count"], int)

    def test_every_point_is_inside_its_single_map_bounds(self):
        for map_id, map_data in self.catalogue["maps"].items():
            self.assertEqual(map_data["bounds"], MAP_BOUNDS[map_id])
            bounds = map_data["bounds"]
            for point in map_data["points"]:
                self.assertLessEqual(bounds["min_x"], point["x"])
                self.assertLessEqual(point["x"], bounds["max_x"])
                self.assertLessEqual(bounds["min_y"], point["y"])
                self.assertLessEqual(point["y"], bounds["max_y"])
                matching_maps = sum(
                    candidate["min_x"] <= point["x"] <= candidate["max_x"]
                    and candidate["min_y"] <= point["y"] <= candidate["max_y"]
                    for candidate in MAP_BOUNDS.values()
                )
                self.assertEqual(matching_maps, 1)

    def test_text_has_no_markup_and_details_and_rewards_are_retained(self):
        for point in self.points:
            for value in (point["name"], point.get("detail", "")):
                self.assertIsNone(re.search(r"<[^<>]*>", value))
            for reward in point.get("rewards", []):
                self.assertIsNone(re.search(r"<[^<>]*>", reward["name"]))

        by_name = {point["name"]: point for point in self.points}
        self.assertEqual(by_name["Chillet"]["detail"], "Field Alpha · Ice / Dragon")
        self.assertEqual(by_name["Chillet"]["level"], 11)
        shrine = by_name["Crossbow Schematic 3"]
        self.assertEqual(shrine["detail"], "+20 Dog Coin")
        self.assertEqual(
            shrine["rewards"],
            [
                {"name": "Crossbow Schematic 3", "count": 1},
                {"name": "Dog Coin", "count": 20},
            ],
        )
        journal = by_name["Marcus Dryden's Diary - 3"]
        self.assertIn("Horus", journal["detail"])
        self.assertNotIn("characterName", journal["detail"])

    def test_missing_source_preserves_existing_output(self):
        with TemporaryDirectory() as directory:
            output = Path(directory) / "map-points.json"
            output.write_text("known-good\n", encoding="utf-8")
            with self.assertRaises(CommandError):
                call_command(
                    "build_map_catalogue",
                    source=str(Path(directory) / "missing"),
                    output=str(output),
                    verbosity=0,
                )
            self.assertEqual(output.read_text(encoding="utf-8"), "known-good\n")
