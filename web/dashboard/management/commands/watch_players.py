import logging
import time
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import close_old_connections
from django.utils import timezone

from dashboard.accounts import get_user_profile
from dashboard.models import UserProfile
from dashboard.palworld_api import PalworldAPIClient, PalworldAPIError

logger = logging.getLogger(__name__)
User = get_user_model()


class Command(BaseCommand):
    help = "Poll Palworld REST API, kick non-registered players, send welcome messages"

    def handle(self, *args, **options):
        if not settings.PALWORLD_API_URL or not settings.PALWORLD_API_PASSWORD:
            logger.warning("Palworld API not configured, watcher exiting")
            return

        client = PalworldAPIClient()
        poll_seconds = settings.PALWORLD_WATCHER_POLL_SECONDS
        grace_seconds = settings.PALWORLD_KICK_GRACE_SECONDS
        kick_enabled = settings.PALWORLD_KICK_UNREGISTERED

        seen_players = {}
        welcomed = set()

        logger.info(
            "Player watcher started (poll=%ds, grace=%ds, kick=%s)",
            poll_seconds, grace_seconds, kick_enabled,
        )

        while True:
            try:
                close_old_connections()
                players = client.get_players()
                now = timezone.now()
                registered_names = self._registered_names()

                current_uids = set()
                for player in players:
                    uid = player.get("userId", player.get("playerId", ""))
                    name = player.get("name", player.get("playerName", ""))
                    current_uids.add(uid)

                    is_registered = name.casefold() in registered_names

                    if uid not in seen_players:
                        seen_players[uid] = {
                            "name": name,
                            "first_seen": now,
                            "is_registered": is_registered,
                        }
                        logger.info("Player joined: %s (uid=%s, registered=%s)", name, uid, is_registered)
                    else:
                        seen_players[uid]["is_registered"] = name.casefold() in registered_names

                    if is_registered and uid not in welcomed:
                        try:
                            client.announce(f"Benvenuto {name} sul server!")
                            welcomed.add(uid)
                        except PalworldAPIError:
                            pass

                    if not is_registered and kick_enabled:
                        first_seen = seen_players[uid]["first_seen"]
                        elapsed = (now - first_seen).total_seconds()
                        if elapsed >= grace_seconds:
                            remaining = int(grace_seconds - elapsed)
                            if remaining > -30:
                                try:
                                    client.announce(
                                        f"{name}: registrati sul sito web con lo stesso nome utente "
                                        f"per giocare su questo server. Verrai disconnesso tra pochi secondi."
                                    )
                                except PalworldAPIError:
                                    pass
                            if elapsed >= grace_seconds + 10:
                                try:
                                    client.kick(uid)
                                    logger.info("Kicked non-registered player %s (uid=%s)", name, uid)
                                except PalworldAPIError as exc:
                                    logger.warning("Kick failed for %s: %s", name, exc)

                gone_uids = set(seen_players.keys()) - current_uids
                for uid in gone_uids:
                    name = seen_players[uid]["name"]
                    logger.info("Player left: %s (uid=%s)", name, uid)
                    welcomed.discard(uid)
                    del seen_players[uid]

            except PalworldAPIError as exc:
                logger.warning("Palworld API error: %s", exc)
            except Exception:
                logger.exception("Unexpected error in player watcher")

            time.sleep(poll_seconds)

    def _registered_names(self):
        try:
            profiles = UserProfile.objects.filter(
                email_verified=True, approved=True
            ).select_related("user")
            return {p.user.username.casefold() for p in profiles}
        except Exception:
            logger.exception("Failed to fetch registered names")
            return set()
