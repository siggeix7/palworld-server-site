import hashlib
import json
import math
import re
import tempfile
from collections import Counter
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError


SOURCE_REPOSITORY = "https://github.com/LukeHollandDev/palworld-live-map"
SOURCE_REVISION = "19f3e3f8e684481bde58fef6c76845f811d57614"
GAME_VERSION = "1.0.1.100619"
LANDMARKS_PATH = Path("assets/palworld/landmarks")

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
EXPECTED_TOTAL = 1146
EXPECTED_MAP_COUNTS = {"palpagos": 1064, "world-tree": 82}
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
EXPECTED_FILES = {
    "encounter-additions": {
        "file": "encounter-additions.json",
        "count": 36,
        "sha256": "eeb1906170253c7e395385707241b4a07bc6d6c1a946d9317dd07b29f0751069",
    },
    "navigation": {
        "file": "navigation.json",
        "count": 344,
        "sha256": "e028d877902bddfd96baad2921ab087b60b7bbe33ec5b27e7fe4e26136a8c611",
    },
    "collectibles": {
        "file": "collectibles.json",
        "count": 577,
        "sha256": "1c8216b375e937545a6ae4bbcc28a5a2b703ed17051e9e161a2d5a1e2aa2bab1",
    },
    "npc-locations": {
        "file": "npc-locations.json",
        "count": 90,
        "sha256": "5f9db83e2c997fad6d0e440825529f61e3485c65b3caaeb01a68ce30fc636ca6",
    },
}
EXPECTED_MANIFEST_HASHES = {
    "manifest.json": "d49941e2378850a79bea9bda1c296249763805f52ca9ca5223ce553608112ddd",
    "catalogue/manifest.json": "16113252b5902f4d96d27a6e38bec777294dc3a39b477c433c030e014e883e1e",
}

CHARACTER_NAME_RE = re.compile(
    r"<characterName\s+id=(?:\"([^\"]+)\"|'([^']+)'|([^/\s>]+))\s*/>",
    re.IGNORECASE,
)
TAG_RE = re.compile(r"<[^<>]*>")


def _read_json(path, expected_sha256=None):
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise CommandError(f"Cannot read source file {path}: {exc}") from exc

    digest = hashlib.sha256(raw).hexdigest()
    if expected_sha256 and digest != expected_sha256:
        raise CommandError(
            f"SHA256 mismatch for {path}: expected {expected_sha256}, got {digest}"
        )
    try:
        return json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CommandError(f"Invalid JSON in {path}: {exc}") from exc


def _require(condition, message):
    if not condition:
        raise CommandError(message)


def _locations(document, label):
    _require(isinstance(document, dict), f"{label} must contain a JSON object")
    locations = document.get("locations")
    _require(isinstance(locations, list), f"{label} locations must be a list")
    return locations


def _number(value, label, decimal_places=4):
    _require(
        isinstance(value, (int, float)) and not isinstance(value, bool),
        f"{label} must be numeric",
    )
    _require(math.isfinite(value), f"{label} must be finite")
    rounded = round(value, decimal_places)
    return 0 if rounded == 0 else rounded


def _text(value, label):
    _require(isinstance(value, str) and value.strip(), f"{label} must be non-empty text")

    def replace_character(match):
        return next(group for group in match.groups() if group is not None)

    sanitized = CHARACTER_NAME_RE.sub(replace_character, value)
    sanitized = TAG_RE.sub("", sanitized).strip()
    _require(sanitized, f"{label} is empty after markup sanitization")
    return sanitized


def _point_id(kind, source_id):
    digest = hashlib.sha256(f"{kind}\0{source_id}".encode()).hexdigest()[:20]
    return f"{kind}-{digest}"


class Command(BaseCommand):
    help = "Build the deterministic static Palworld map point catalogue"

    def add_arguments(self, parser):
        parser.add_argument(
            "--source",
            required=True,
            type=Path,
            help="Path to the pinned palworld-live-map repository root",
        )
        parser.add_argument(
            "--output",
            type=Path,
            default=(
                Path(__file__).resolve().parents[2]
                / "static/dashboard/data/map-points.json"
            ),
            help="Output JSON path",
        )

    def handle(self, *args, **options):
        source_root = Path(options["source"]).expanduser()
        output_path = Path(options["output"]).expanduser()
        landmarks_dir = source_root / LANDMARKS_PATH
        catalogue_dir = landmarks_dir / "catalogue"

        landmark_manifest = _read_json(
            landmarks_dir / "manifest.json",
            EXPECTED_MANIFEST_HASHES["manifest.json"],
        )
        catalogue_manifest = _read_json(
            catalogue_dir / "manifest.json",
            EXPECTED_MANIFEST_HASHES["catalogue/manifest.json"],
        )
        self._validate_manifests(landmark_manifest, catalogue_manifest)

        source_locations = list(_locations(landmark_manifest, "landmark manifest"))
        declared_datasets = {
            dataset["id"]: dataset for dataset in catalogue_manifest["datasets"]
        }
        for dataset_id, expected in EXPECTED_FILES.items():
            declared = declared_datasets[dataset_id]
            document = _read_json(
                catalogue_dir / expected["file"], expected["sha256"]
            )
            _require(document.get("schemaVersion") == 1, f"Invalid schema for {dataset_id}")
            _require(document.get("id") == dataset_id, f"Invalid dataset id for {dataset_id}")
            locations = _locations(document, dataset_id)
            _require(
                len(locations) == declared["count"],
                f"Count mismatch for {dataset_id}: expected {declared['count']}, got {len(locations)}",
            )
            source_locations.extend(locations)

        points_by_map = self._build_points(source_locations)
        payload = {
            "schema_version": 3,
            "source": {
                "repository": SOURCE_REPOSITORY,
                "revision": SOURCE_REVISION,
                "game_version": GAME_VERSION,
            },
            "total_count": EXPECTED_TOTAL,
            "category_counts": EXPECTED_CATEGORY_COUNTS,
            "maps": {
                map_id: {
                    "bounds": bounds,
                    "point_count": len(points_by_map[map_id]),
                    "points": points_by_map[map_id],
                }
                for map_id, bounds in MAP_BOUNDS.items()
            },
        }

        temporary_path = None
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=output_path.parent,
                prefix=f".{output_path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
                temporary.write(
                    json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
                    + "\n"
                )
            temporary_path.chmod(0o644)
            temporary_path.replace(output_path)
        except OSError as exc:
            raise CommandError(f"Cannot write catalogue to {output_path}: {exc}") from exc
        finally:
            if temporary_path:
                temporary_path.unlink(missing_ok=True)

        self.stdout.write(
            self.style.SUCCESS(f"Wrote {EXPECTED_TOTAL} map points to {output_path}")
        )

    def _validate_manifests(self, landmark_manifest, catalogue_manifest):
        _require(
            isinstance(landmark_manifest, dict)
            and landmark_manifest.get("schemaVersion") == 2,
            "Invalid landmark manifest schema",
        )
        _require(
            landmark_manifest.get("gameVersion") == GAME_VERSION,
            f"Landmark manifest gameVersion must be {GAME_VERSION}",
        )
        _require(
            isinstance(catalogue_manifest, dict)
            and catalogue_manifest.get("schemaVersion") == 1,
            "Invalid catalogue manifest schema",
        )
        _require(
            catalogue_manifest.get("gameVersion") == GAME_VERSION,
            f"Catalogue manifest gameVersion must be {GAME_VERSION}",
        )

        datasets = catalogue_manifest.get("datasets")
        _require(isinstance(datasets, list), "Catalogue manifest datasets must be a list")
        _require(
            all(isinstance(dataset, dict) and "id" in dataset for dataset in datasets),
            "Catalogue manifest contains an invalid dataset declaration",
        )
        _require(
            len({dataset["id"] for dataset in datasets}) == len(datasets),
            "Catalogue manifest contains duplicate dataset ids",
        )
        declared = {dataset["id"]: dataset for dataset in datasets}
        _require(
            set(declared) == set(EXPECTED_FILES),
            "Catalogue manifest must declare exactly the expected datasets",
        )
        for dataset_id, expected in EXPECTED_FILES.items():
            dataset = declared[dataset_id]
            for field in ("file", "count", "sha256"):
                _require(
                    dataset.get(field) == expected[field],
                    f"Unexpected {field} declaration for {dataset_id}",
                )

    def _build_points(self, source_locations):
        _require(
            len(source_locations) == EXPECTED_TOTAL,
            f"Expected {EXPECTED_TOTAL} source points, got {len(source_locations)}",
        )
        category_counts = Counter()
        points_by_map = {map_id: [] for map_id in MAP_BOUNDS}
        output_ids = set()

        for index, location in enumerate(source_locations):
            _require(isinstance(location, dict), f"Point {index} must be an object")
            kind = location.get("kind", location.get("category"))
            _require(kind in EXPECTED_CATEGORY_COUNTS, f"Unexpected point category {kind!r}")
            source_id = location.get("id")
            _require(
                isinstance(source_id, str) and source_id,
                f"Point {index} has an invalid source id",
            )
            x = _number(location.get("x"), f"{source_id} x")
            y = _number(location.get("y"), f"{source_id} y")
            matching_maps = [
                map_id
                for map_id, bounds in MAP_BOUNDS.items()
                if bounds["min_x"] <= x <= bounds["max_x"]
                and bounds["min_y"] <= y <= bounds["max_y"]
            ]
            _require(
                len(matching_maps) == 1,
                f"Point {source_id} must map to exactly one region; got {matching_maps}",
            )

            point = {
                "id": _point_id(kind, source_id),
                "kind": kind,
                "x": x,
                "y": y,
                "name": _text(location.get("name"), f"{source_id} name"),
            }
            if "detail" in location:
                point["detail"] = _text(location["detail"], f"{source_id} detail")
            if "level" in location:
                level = location["level"]
                _require(
                    isinstance(level, int) and not isinstance(level, bool) and level >= 0,
                    f"{source_id} level must be a non-negative integer",
                )
                point["level"] = level
            if "z" in location:
                point["z"] = _number(location["z"], f"{source_id} z")
            if "rewards" in location:
                rewards = location["rewards"]
                _require(isinstance(rewards, list) and rewards, f"{source_id} rewards must be a list")
                point["rewards"] = [
                    self._sanitize_reward(reward, source_id, reward_index)
                    for reward_index, reward in enumerate(rewards)
                ]

            _require(point["id"] not in output_ids, f"Stable id collision for {source_id}")
            output_ids.add(point["id"])
            category_counts[kind] += 1
            points_by_map[matching_maps[0]].append(point)

        _require(
            dict(category_counts) == EXPECTED_CATEGORY_COUNTS,
            f"Category counts do not match: {dict(category_counts)}",
        )
        for map_id, expected_count in EXPECTED_MAP_COUNTS.items():
            _require(
                len(points_by_map[map_id]) == expected_count,
                f"Expected {expected_count} {map_id} points, got {len(points_by_map[map_id])}",
            )
            points_by_map[map_id].sort(
                key=lambda point: (
                    point["kind"],
                    point["name"].casefold(),
                    point["x"],
                    point["y"],
                    point["id"],
                )
            )
        return points_by_map

    def _sanitize_reward(self, reward, source_id, reward_index):
        _require(
            isinstance(reward, dict),
            f"{source_id} reward {reward_index} must be an object",
        )
        count = reward.get("count")
        _require(
            isinstance(count, int) and not isinstance(count, bool) and count > 0,
            f"{source_id} reward {reward_index} count must be a positive integer",
        )
        return {
            "name": _text(
                reward.get("name"), f"{source_id} reward {reward_index} name"
            ),
            "count": count,
        }
