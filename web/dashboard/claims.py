import hashlib
import ipaddress
import json
import re
import secrets
from datetime import timedelta, timezone as datetime_timezone
from functools import lru_cache

from django.conf import settings
from django.db import OperationalError, transaction
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from .live_map import _catalogue_asset
from .models import ClaimChallenge, ClaimSession, ClaimThrottle, Player, PlayerClaimData


CLAIM_BODY_LIMIT = 8 << 10
CLAIM_PLAYER_ID_LIMIT = 256
CLAIM_QUESTION_ID_LIMIT = 64
CLAIM_BEARER_PATTERN = re.compile(r"^[A-Za-z0-9_-]{43}$")
PUBLIC_PLAYER_ID_PATTERN = re.compile(r"^[0-9a-f]{24}$")
CLAIM_CHALLENGE_TTL = timedelta(minutes=10)
CLAIM_SESSION_IDLE_TTL = timedelta(hours=24)
CLAIM_SESSION_ABSOLUTE_TTL = timedelta(days=7)
CLAIM_DATA_STALE_AFTER = timedelta(minutes=15)
MAX_CHALLENGES = 1024
MAX_SESSIONS = 4096
CLAIM_THROTTLE_RETENTION = timedelta(hours=1)
MAX_QUIZ_ANSWERS = 1
MIN_QUIZ_OPTIONS = 3
MAX_QUIZ_OPTIONS = 8
MAX_COMMON_SLOTS = 12
MAX_QUIZ_FACTS = 24
PROGRESS_DOMAINS = (
    ("alpha-pals", "alpha-pals", "normal_bosses"),
    ("bosses", "bosses", "tower_bosses"),
    ("bounties", "bounties", "normal_bosses"),
    ("watchtowers", "watchtowers", "fast_travel"),
    ("waypoints", "waypoints", "fast_travel"),
    ("effigies", "effigies", "relics"),
    ("journals", "journals", "notes"),
    ("ancient-shrine-pickups", "ancient-shrine-pickups", "item_pickups"),
)
PROGRESS_KEYS = {
    "fast_travel": "watchtowers",
    "areas": None,
    "notes": "journals",
    "relics": "effigies",
    "item_pickups": "ancient-shrine-pickups",
    "normal_bosses": "bounties",
    "tower_bosses": "bosses",
}


class ClaimError(Exception):
    def __init__(self, code, status):
        super().__init__(code)
        self.code = code
        self.status = status


def _private(response):
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Pragma"] = "no-cache"
    return response


def _error(code, status, retry_after=None):
    response = _private(JsonResponse({"error": code}, status=status))
    if retry_after is not None:
        response.headers["Retry-After"] = str(retry_after)
    return response


def _enabled():
    return bool(getattr(settings, "PLAYER_CLAIMS_ENABLED", False))


def _is_bearer(value):
    return isinstance(value, str) and bool(CLAIM_BEARER_PATTERN.fullmatch(value))


def _hash_bearer(value):
    return hashlib.sha256(value.encode("ascii")).hexdigest()


def _new_bearer():
    return secrets.token_urlsafe(32)


def _authorization_bearer(request):
    scheme, separator, value = request.headers.get("Authorization", "").partition(" ")
    if not separator or scheme.casefold() != "bearer":
        return ""
    return value.strip()


def _request_source(request):
    remote = request.META.get("REMOTE_ADDR", "unknown")
    forwarded = request.headers.get("X-Forwarded-For", "")
    if remote in getattr(settings, "AUTH_TRUSTED_PROXY_ADDRESSES", set()) and forwarded:
        remote = forwarded.rsplit(",", 1)[-1].strip() or remote
    try:
        address = ipaddress.ip_address(remote)
        if address.version == 6:
            return str(ipaddress.ip_network(f"{address}/64", strict=False))
        return str(address)
    except ValueError:
        return remote[:128]


def _throttle_key(scope, source):
    return hashlib.sha256(
        f"{settings.SECRET_KEY}:player-claims:{scope}:{source}".encode("utf-8")
    ).hexdigest()


def _allow_request(request, scope, source_limit, source_window, global_limit, global_window):
    now = timezone.now()
    entries = (
        (_throttle_key(scope, _request_source(request)), source_limit, source_window),
        (_throttle_key(scope, "global"), global_limit, global_window),
    )
    try:
        with transaction.atomic():
            ClaimThrottle.objects.filter(
                window_started_at__lte=now - CLAIM_THROTTLE_RETENTION
            ).delete()
            throttles = []
            retry_after = 0
            for key, limit, window in entries:
                throttle, _ = ClaimThrottle.objects.select_for_update().get_or_create(
                    key=key,
                    defaults={"window_started_at": now, "attempts": 0},
                )
                if throttle.window_started_at <= now - window:
                    throttle.window_started_at = now
                    throttle.attempts = 0
                if throttle.attempts >= limit:
                    retry_after = max(
                        retry_after,
                        max(1, int((throttle.window_started_at + window - now).total_seconds())),
                    )
                throttles.append(throttle)
            if retry_after:
                return False, retry_after
            for throttle in throttles:
                throttle.attempts += 1
                throttle.save(update_fields=["window_started_at", "attempts"])
        return True, 0
    except OperationalError:
        return False, 60


def _reject_json_constant(value):
    raise ValueError(f"unsupported JSON constant: {value}")


def _unique_json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _decode_json(request):
    if request.content_type.lower() != "application/json":
        raise ClaimError("invalid_request", 415)
    content_length = request.META.get("CONTENT_LENGTH")
    try:
        if content_length and int(content_length) > CLAIM_BODY_LIMIT:
            raise ClaimError("invalid_request", 400)
    except ValueError as exc:
        raise ClaimError("invalid_request", 400) from exc
    if len(request.body) > CLAIM_BODY_LIMIT:
        raise ClaimError("invalid_request", 400)
    try:
        body = json.loads(
            request.body or b"{}",
            parse_constant=_reject_json_constant,
            object_pairs_hook=_unique_json_object,
        )
    except (ValueError, UnicodeDecodeError) as exc:
        raise ClaimError("invalid_request", 400) from exc
    if not isinstance(body, dict):
        raise ClaimError("invalid_request", 400)
    return body


def _valid_public_player_id(value):
    return isinstance(value, str) and len(value) <= CLAIM_PLAYER_ID_LIMIT and bool(
        PUBLIC_PLAYER_ID_PATTERN.fullmatch(value)
    )


def _valid_question_id(value):
    return (
        isinstance(value, str)
        and 0 < len(value) <= CLAIM_QUESTION_ID_LIMIT
        and value == value.strip()
        and all(character.isprintable() for character in value)
    )


def _subject(public_player_id):
    return hmac_digest(
        b"palworld-live-map/player-claim-subject/v1\x00" + public_player_id.encode("ascii")
    )


def hmac_digest(value):
    import hmac

    return hmac.new(settings.SECRET_KEY.encode("utf-8"), value, hashlib.sha256).hexdigest()


def _iso(value):
    return value.astimezone(datetime_timezone.utc).isoformat().replace("+00:00", "Z")


def _humanize(value):
    value = str(value or "").strip()
    if not value:
        return ""
    result = []
    previous = ""
    for current in value:
        if current in "_-":
            if result and previous != " ":
                result.append(" ")
                previous = " "
            continue
        if result and current.isupper() and (previous.islower() or previous.isdigit()):
            result.append(" ")
        result.append(current)
        previous = current
    return " ".join("".join(result).split())


def _unique_options(values):
    options = []
    seen = set()
    for value in values:
        label = _humanize(value)
        key = label.casefold()
        if label and key not in seen:
            seen.add(key)
            options.append(label)
    return options


def _valid_stack(stack):
    return (
        isinstance(stack, dict)
        and isinstance(stack.get("slot"), int)
        and not isinstance(stack.get("slot"), bool)
        and 0 <= stack["slot"] <= 1023
        and isinstance(stack.get("item_id"), str)
        and bool(stack["item_id"].strip())
        and isinstance(stack.get("count"), int)
        and not isinstance(stack.get("count"), bool)
        and stack["count"] > 0
    )


def _xorshift(state):
    mask = (1 << 64) - 1
    state ^= state >> 12
    state ^= (state << 25) & mask
    state ^= state >> 27
    return (state * 0x2545F4914F6CDD1D) & mask


def _shuffle(values, state):
    for index in range(len(values) - 1, 0, -1):
        state = _xorshift(state)
        other = state % (index + 1)
        values[index], values[other] = values[other], values[index]
    return state


def _candidate(prompt, value, options, question_id, state):
    value = _humanize(value)
    if not value:
        return None, state
    decoys = [option for option in options if option.casefold() != value.casefold()]
    state = _shuffle(decoys, state)
    selected = [value]
    seen = {value.casefold()}
    for option in decoys:
        key = option.casefold()
        if key in seen:
            continue
        selected.append(option)
        seen.add(key)
        if len(selected) == MAX_QUIZ_OPTIONS:
            break
    if len(selected) < MIN_QUIZ_OPTIONS:
        return None, state
    state = _shuffle(selected, state)
    correct = next((index for index, option in enumerate(selected) if option.casefold() == value.casefold()), -1)
    if correct < 0:
        return None, state
    return {
        "question": {
            "id": question_id,
            "prompt": prompt,
            "options": selected,
            "canCycle": False,
        },
        "correct": correct,
    }, state


def _build_quiz(payload, snapshot_at, selector):
    if not snapshot_at:
        raise ClaimError("claim_unavailable", 503)
    inventory = payload.get("inventory", {}) if isinstance(payload, dict) else {}
    if not isinstance(inventory, dict):
        raise ClaimError("claim_unavailable", 503)
    facts = []
    common = [stack for stack in inventory.get("common", []) if _valid_stack(stack) and stack["slot"] < MAX_COMMON_SLOTS]
    for key, prompt in (
        ("common", "What was in inventory slot %d?"),
        ("weapons", "What was in loadout slot %d?"),
        ("armor", "What was equipped in equipment slot %d?"),
        ("food", "What was in food pouch slot %d?"),
    ):
        stacks = common if key == "common" else [stack for stack in inventory.get(key, []) if _valid_stack(stack)]
        options = _unique_options(stack["item_id"] for stack in stacks)
        if len(options) < MIN_QUIZ_OPTIONS:
            continue
        for stack in stacks:
            facts.append((prompt % (stack["slot"] + 1), stack["item_id"], options))

    party = payload.get("party", []) if isinstance(payload, dict) else []
    if isinstance(party, list):
        party_entries = [
            pal for pal in party
            if isinstance(pal, dict)
            and isinstance(pal.get("slot"), int)
            and not isinstance(pal.get("slot"), bool)
            and pal["slot"] >= 0
            and isinstance(pal.get("species"), str)
            and pal["species"].strip()
        ]
        options = _unique_options(pal["species"] for pal in party_entries)
        if len(options) >= MIN_QUIZ_OPTIONS:
            for pal in party_entries:
                facts.append((f"Which Pal species was in party slot {pal['slot'] + 1}?", pal["species"], options))

    if not facts:
        raise ClaimError("no_suitable_question", 409)
    state = (selector ^ 0xD1B54A32D192ED03) & ((1 << 64) - 1)
    state = _shuffle(facts, state)
    facts = facts[:MAX_QUIZ_FACTS]
    candidates = []
    for index, (prompt, value, options) in enumerate(facts, start=1):
        candidate, state = _candidate(prompt, value, options, f"q{index}", state)
        if candidate:
            candidates.append(candidate)
    if not candidates:
        raise ClaimError("no_suitable_question", 409)
    current = candidates[0]
    remaining = candidates[1:]
    current["question"]["canCycle"] = bool(remaining)
    return current, remaining


def _claim_data(public_player_id):
    try:
        data = PlayerClaimData.objects.get(public_id=public_player_id)
    except PlayerClaimData.DoesNotExist as exc:
        raise ClaimError("claim_unavailable", 503) from exc
    if timezone.now() - data.updated_at > CLAIM_DATA_STALE_AFTER:
        raise ClaimError("claim_unavailable", 503)
    if not isinstance(data.payload, dict):
        raise ClaimError("claim_unavailable", 503)
    return data


def _cleanup_expired():
    now = timezone.now()
    ClaimChallenge.objects.filter(expires_at__lte=now).delete()
    ClaimSession.objects.filter(
        idle_expires_at__lte=now
    ).delete()
    ClaimSession.objects.filter(absolute_expires_at__lte=now).delete()


def _session(bearer, lock=False):
    if not _is_bearer(bearer):
        raise ClaimError("authentication_required", 401)
    try:
        queryset = ClaimSession.objects
        if lock:
            queryset = queryset.select_for_update()
        session = queryset.get(bearer_hash=_hash_bearer(bearer))
    except ClaimSession.DoesNotExist as exc:
        raise ClaimError("authentication_required", 401) from exc
    now = timezone.now()
    if session.idle_expires_at <= now or session.absolute_expires_at <= now:
        session.delete()
        raise ClaimError("authentication_required", 401)
    session.idle_expires_at = min(now + CLAIM_SESSION_IDLE_TTL, session.absolute_expires_at)
    session.save(update_fields=["idle_expires_at"])
    return session


@lru_cache(maxsize=1)
def _progress_records():
    path = settings.BASE_DIR / "dashboard/data/live-map-progress.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ClaimError("progress_unavailable", 503) from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("catalogueHash"), str):
        raise ClaimError("progress_unavailable", 503)
    records = payload.get("records")
    if not isinstance(records, list):
        raise ClaimError("progress_unavailable", 503)
    result = []
    for record in records:
        if (
            not isinstance(record, dict)
            or not isinstance(record.get("id"), str)
            or not isinstance(record.get("category"), str)
            or not isinstance(record.get("stateKey"), str)
            or not record["id"]
            or not record["stateKey"]
        ):
            raise ClaimError("progress_unavailable", 503)
        result.append(record)
    return payload["catalogueHash"], result


def _progress_response(data):
    catalogue_data, catalogue_hash = _catalogue_asset()
    del catalogue_data
    sidecar_hash, records = _progress_records()
    if sidecar_hash != catalogue_hash:
        raise ClaimError("progress_unavailable", 503)
    payload = data.payload
    progress = payload.get("progress")
    if not isinstance(progress, dict):
        raise ClaimError("progress_unavailable", 503)
    completed_by_key = {}
    for key, category in PROGRESS_KEYS.items():
        if category is None:
            continue
        values = progress.get(key)
        if not isinstance(values, list):
            raise ClaimError("progress_unavailable", 503)
        completed_by_key[key] = {
            str(value).strip().casefold()
            for value in values
            if isinstance(value, str) and value.strip()
        }
    domains = []
    for domain_id, category, progress_key in PROGRESS_DOMAINS:
        category_records = [record for record in records if record["category"] == category]
        completed = sorted(
            record["id"]
            for record in category_records
            if record["stateKey"].casefold() in completed_by_key.get(progress_key, set())
        )
        domains.append({
            "id": domain_id,
            "coverage": "complete",
            "completedIds": completed,
            "total": len(category_records),
        })
    return {
        "snapshotAt": _iso(data.snapshot_at),
        "catalogueVersion": catalogue_hash,
        "domains": domains,
    }


def _start_error(exc):
    if isinstance(exc, ClaimError):
        return _error(exc.code, exc.status)
    return _error("claim_unavailable", 503)


@require_POST
@never_cache
def start_player_claim(request):
    if not _enabled():
        return _error("claim_unavailable", 503)
    allowed, retry_after = _allow_request(
        request, "start", 5, timedelta(minutes=10), 100, timedelta(minutes=1)
    )
    if not allowed:
        return _error("claim_unavailable", 429, retry_after)
    try:
        body = _decode_json(request)
        if set(body) != {"playerId"} or not _valid_public_player_id(body.get("playerId")):
            raise ClaimError("invalid_request", 400)
        player_id = body["playerId"]
        if not Player.objects.filter(public_id=player_id).exists():
            raise ClaimError("claim_unavailable", 503)
        data = _claim_data(player_id)
        _cleanup_expired()
        if ClaimChallenge.objects.count() >= MAX_CHALLENGES:
            raise ClaimError("claim_unavailable", 429)
        for _ in range(3):
            token = _new_bearer()
            token_hash = _hash_bearer(token)
            if ClaimChallenge.objects.filter(bearer_hash=token_hash).exists():
                continue
            if ClaimSession.objects.filter(bearer_hash=token_hash).exists():
                continue
            current, remaining = _build_quiz(data.payload, data.snapshot_at, secrets.randbits(64))
            expires_at = timezone.now() + CLAIM_CHALLENGE_TTL
            ClaimChallenge.objects.create(
                bearer_hash=token_hash,
                subject=_subject(player_id),
                public_player_id=player_id,
                question=current["question"],
                correct_answer=current["correct"],
                remaining_questions=remaining,
                expires_at=expires_at,
            )
            return _private(JsonResponse({
                "challengeToken": token,
                "status": "ready",
                "instructions": {
                    "kind": "inventory_quiz",
                    "questions": [current["question"]],
                    "snapshotAt": _iso(data.snapshot_at),
                },
                "expiresAt": _iso(expires_at),
            }, status=201))
        raise ClaimError("claim_unavailable", 503)
    except ClaimError as exc:
        return _start_error(exc)
    except (OperationalError, ValueError, TypeError, OverflowError):
        return _error("claim_unavailable", 503)


@require_POST
@never_cache
def cycle_player_claim_question(request):
    if not _enabled():
        return _error("claim_unavailable", 503)
    allowed, retry_after = _allow_request(
        request, "verify", 60, timedelta(minutes=10), 600, timedelta(minutes=1)
    )
    if not allowed:
        return _error("claim_unavailable", 429, retry_after)
    try:
        body = _decode_json(request)
        if set(body) != {"challengeToken", "questionId"} or not _is_bearer(body.get("challengeToken")) or not _valid_question_id(body.get("questionId")):
            raise ClaimError("invalid_request", 400)
        with transaction.atomic():
            challenge = ClaimChallenge.objects.select_for_update().get(
                bearer_hash=_hash_bearer(body["challengeToken"])
            )
            if challenge.expires_at <= timezone.now():
                challenge.delete()
                return _error("invalid_or_expired_challenge", 401)
            if challenge.verifying:
                raise ClaimError("question_busy", 409)
            if challenge.question.get("id") != body["questionId"]:
                raise ClaimError("invalid_request", 400)
            remaining = challenge.remaining_questions if isinstance(challenge.remaining_questions, list) else []
            if not remaining:
                raise ClaimError("no_alternate_question", 409)
            next_question = remaining.pop(0)
            question = next_question.get("question") if isinstance(next_question, dict) else None
            correct = next_question.get("correct") if isinstance(next_question, dict) else None
            if not isinstance(question, dict) or not isinstance(correct, int):
                raise ClaimError("claim_unavailable", 503)
            question["canCycle"] = bool(remaining)
            challenge.question = question
            challenge.correct_answer = correct
            challenge.remaining_questions = remaining
            challenge.save(update_fields=["question", "correct_answer", "remaining_questions"])
            data = _claim_data(challenge.public_player_id)
            return _private(JsonResponse({
                "status": "ready",
                "instructions": {
                    "kind": "inventory_quiz",
                    "questions": [question],
                    "snapshotAt": _iso(data.snapshot_at),
                },
                "expiresAt": _iso(challenge.expires_at),
            }))
    except ClaimChallenge.DoesNotExist:
        return _error("invalid_or_expired_challenge", 401)
    except ClaimError as exc:
        return _error(exc.code, exc.status)
    except (OperationalError, ValueError, TypeError):
        return _error("claim_unavailable", 503)


@require_POST
@never_cache
def verify_player_claim(request):
    if not _enabled():
        return _error("claim_unavailable", 503)
    allowed, retry_after = _allow_request(
        request, "verify", 60, timedelta(minutes=10), 600, timedelta(minutes=1)
    )
    if not allowed:
        return _error("claim_unavailable", 429, retry_after)
    try:
        body = _decode_json(request)
        if set(body) != {"challengeToken", "answers"} or not _is_bearer(body.get("challengeToken")):
            raise ClaimError("invalid_request", 400)
        answers = body.get("answers", [])
        if not isinstance(answers, list) or len(answers) != MAX_QUIZ_ANSWERS:
            raise ClaimError("invalid_request", 400)
        for answer in answers:
            if (
                not isinstance(answer, dict)
                or set(answer) != {"questionId", "option"}
                or not _valid_question_id(answer.get("questionId"))
                or not isinstance(answer.get("option"), int)
                or isinstance(answer.get("option"), bool)
            ):
                raise ClaimError("invalid_request", 400)
        with transaction.atomic():
            challenge = ClaimChallenge.objects.select_for_update().get(
                bearer_hash=_hash_bearer(body["challengeToken"])
            )
            if challenge.expires_at <= timezone.now():
                challenge.delete()
                return _error("invalid_or_expired_challenge", 401)
            answer = answers[0] if answers else None
            correct = bool(
                answer
                and answer["questionId"] == challenge.question.get("id")
                and answer["option"] == challenge.correct_answer
            )
            if not correct:
                challenge.delete()
                return _error("verification_failed", 401)
            _cleanup_expired()
            if ClaimSession.objects.count() >= MAX_SESSIONS:
                raise ClaimError("claim_unavailable", 503)
            session_token = _new_bearer()
            session_hash = _hash_bearer(session_token)
            if ClaimSession.objects.filter(bearer_hash=session_hash).exists():
                raise ClaimError("claim_unavailable", 503)
            now = timezone.now()
            absolute = now + CLAIM_SESSION_ABSOLUTE_TTL
            idle = min(now + CLAIM_SESSION_IDLE_TTL, absolute)
            ClaimSession.objects.create(
                bearer_hash=session_hash,
                subject=challenge.subject,
                public_player_id=challenge.public_player_id,
                idle_expires_at=idle,
                absolute_expires_at=absolute,
            )
            challenge.delete()
            return _private(JsonResponse({
                "status": "verified",
                "idleExpiresAt": _iso(idle),
                "absoluteExpiresAt": _iso(absolute),
                "sessionToken": session_token,
            }))
    except ClaimChallenge.DoesNotExist:
        return _error("invalid_or_expired_challenge", 401)
    except ClaimError as exc:
        return _error(exc.code, exc.status)
    except (OperationalError, ValueError, TypeError):
        return _error("claim_unavailable", 503)


@require_GET
@never_cache
def claim_session(request):
    if not _enabled():
        return _error("authentication_required", 401)
    try:
        with transaction.atomic():
            session = _session(_authorization_bearer(request), lock=True)
            return _private(JsonResponse({
                "authenticated": True,
                "playerId": session.public_player_id,
                "idleExpiresAt": _iso(session.idle_expires_at),
                "absoluteExpiresAt": _iso(session.absolute_expires_at),
            }))
    except ClaimError as exc:
        return _error(exc.code, exc.status)
    except (OperationalError, ValueError):
        return _error("authentication_required", 401)


@require_GET
@never_cache
def claim_progress(request):
    if not _enabled():
        return _error("progress_unavailable", 503)
    allowed, retry_after = _allow_request(
        request, "verify", 60, timedelta(minutes=10), 600, timedelta(minutes=1)
    )
    if not allowed:
        return _error("claim_unavailable", 429, retry_after)
    try:
        with transaction.atomic():
            session = _session(_authorization_bearer(request), lock=True)
            data = _claim_data(session.public_player_id)
            return _private(JsonResponse(_progress_response(data)))
    except ClaimError as exc:
        return _error(exc.code, exc.status)
    except (OperationalError, ValueError, TypeError):
        return _error("progress_unavailable", 503)


@require_POST
@never_cache
def logout_claim_session(request):
    if not _enabled():
        return _private(JsonResponse({"authenticated": False}))
    try:
        body = _decode_json(request)
        if body:
            raise ClaimError("invalid_request", 400)
    except ClaimError as exc:
        return _error(exc.code, exc.status)
    bearer = _authorization_bearer(request)
    if _is_bearer(bearer):
        ClaimSession.objects.filter(bearer_hash=_hash_bearer(bearer)).delete()
    return _private(JsonResponse({"authenticated": False}))
