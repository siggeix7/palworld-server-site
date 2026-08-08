from collections import defaultdict
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db.models import Avg
from django.utils import timezone

from dashboard.emails import send_weekly_player_email
from dashboard.models import GuildSnapshot, Player, PlayerSession, PositionSample

WEEKDAY_NAMES = (
    "lunedì",
    "martedì",
    "mercoledì",
    "giovedì",
    "venerdì",
    "sabato",
    "domenica",
)


class Command(BaseCommand):
    help = (
        "Send the personalized weekly Palworld report to the site users whose "
        "player was active in the last 7 days"
    )

    def handle(self, *args, **options):
        now = timezone.now()
        since = now - timedelta(days=7)
        prev_since = since - timedelta(days=7)
        week_window = (since, now)
        prev_window = (prev_since, since)

        sessions = list(
            PlayerSession.objects.filter(
                started_at__lt=now,
                ended_at__gt=prev_since,
            ).select_related("player")
        ) + list(
            PlayerSession.objects.filter(
                started_at__lt=now,
                ended_at__isnull=True,
            ).select_related("player")
        )
        player_sessions = defaultdict(list)
        for session in sessions:
            player_sessions[session.player_id].append(session)

        players = Player.objects.filter(id__in=player_sessions)
        player_map = {player.id: player for player in players}

        def seconds_in(player_id, start, end):
            total = 0
            for session in player_sessions[player_id]:
                stale_end = session.last_seen + timedelta(
                    seconds=settings.DATA_STALE_SECONDS
                )
                session_end = session.ended_at or min(now, stale_end)
                segment_start = max(session.started_at, start)
                segment_end = min(session_end, end)
                if segment_end > segment_start:
                    total += (segment_end - segment_start).total_seconds()
            return total

        week_seconds = {
            player_id: seconds_in(player_id, *week_window)
            for player_id in player_sessions
        }
        prev_seconds = {
            player_id: seconds_in(player_id, *prev_window)
            for player_id in player_sessions
        }
        active = {
            player_id: seconds
            for player_id, seconds in week_seconds.items()
            if seconds > 0
        }
        if not active:
            self.stdout.write("No active players in the last 7 days: no report sent")
            return

        ranking = {
            player_id: position
            for position, player_id in enumerate(
                sorted(active, key=active.get, reverse=True), start=1
            )
        }

        session_stats = self._session_stats(player_sessions, since, now)
        ping_stats = dict(
            PositionSample.objects.filter(
                source_clock__gte=since,
                source_clock__lte=now,
                ping__gt=0,
            )
            .values("player_id")
            .annotate(average_ping=Avg("ping"))
            .values_list("player_id", "average_ping")
        )
        guild_lookup = self._guild_lookup()

        users = {
            user.username.casefold(): user
            for user in get_user_model()
            .objects.filter(is_active=True)
            .exclude(email="")
            .exclude(email__isnull=True)
        }

        top_players = [
            {"name": player_map[player_id].name, "minutes": int(seconds // 60)}
            for player_id, seconds in sorted(
                active.items(), key=lambda item: -item[1]
            )[:5]
        ]

        sent = 0
        for player_id, seconds in sorted(active.items(), key=lambda item: -item[1]):
            player = player_map[player_id]
            user = users.get(player.name.casefold()) or users.get(
                player.account_name.casefold()
            )
            if not user:
                continue
            guild_info = guild_lookup[player.name.casefold()]
            week_minutes = int(seconds // 60)
            prev_minutes = int(prev_seconds[player_id] // 60)
            context = {
                "user_name": user.username,
                "public_site_url": settings.PUBLIC_SITE_URL,
                "since_label": since.strftime("%d/%m/%Y"),
                "until_label": now.strftime("%d/%m/%Y"),
                "week_minutes": week_minutes,
                "week_hours": week_minutes // 60,
                "week_minutes_remainder": week_minutes % 60,
                "prev_minutes": prev_minutes,
                "prev_pct": self._delta_pct(week_minutes, prev_minutes),
                "session_count": session_stats[player_id]["session_count"],
                "longest_session_minutes": session_stats[player_id][
                    "longest_minutes"
                ],
                "active_days": session_stats[player_id]["active_days"],
                "top_day": session_stats[player_id]["top_day"],
                "level": player.level,
                "building_count": player.building_count,
                "avg_ping": round(ping_stats[player_id]) if player_id in ping_stats else None,
                "rank": ranking[player_id],
                "active_total": len(active),
                "guild_name": guild_info["name"],
                "guild_bases": guild_info["bases"],
                "top_players": top_players,
                "is_top_player": any(
                    entry["name"] == player.name for entry in top_players
                ),
            }
            sent += send_weekly_player_email(user, context)
        self.stdout.write(f"Weekly player report sent to {sent} recipient(s)")

    def _session_stats(self, player_sessions, since, now):
        stats = defaultdict(
            lambda: {
                "session_count": 0,
                "longest_minutes": 0,
                "active_days": 0,
                "top_day": "",
            }
        )
        for player_id, sessions in player_sessions.items():
            day_seconds = defaultdict(int)
            seen_days = set()
            for session in sessions:
                stale_end = session.last_seen + timedelta(
                    seconds=settings.DATA_STALE_SECONDS
                )
                session_end = session.ended_at or min(now, stale_end)
                segment_start = max(session.started_at, since)
                segment_end = min(session_end, now)
                if segment_end <= segment_start:
                    continue
                seconds = (segment_end - segment_start).total_seconds()
                stats[player_id]["session_count"] += 1
                stats[player_id]["longest_minutes"] = max(
                    stats[player_id]["longest_minutes"], int(seconds // 60)
                )
                day = session.started_at.astimezone(
                    timezone.get_current_timezone()
                ).date()
                seen_days.add(day)
                day_seconds[day] += seconds
            stats[player_id]["active_days"] = len(seen_days)
            if day_seconds:
                top_day = max(day_seconds, key=day_seconds.get)
                stats[player_id]["top_day"] = WEEKDAY_NAMES[top_day.weekday()]
        return stats

    def _delta_pct(self, current_minutes, previous_minutes):
        if previous_minutes <= 0 or current_minutes == 0:
            return None
        return round((current_minutes - previous_minutes) / previous_minutes * 100)

    def _guild_lookup(self):
        snapshot = GuildSnapshot.objects.first()
        payload = (
            snapshot.payload
            if snapshot and isinstance(snapshot.payload, dict)
            else {}
        )
        saved_guilds = payload.get("guilds", [])
        saved_players = payload.get("players", [])
        if not isinstance(saved_guilds, list) or not isinstance(saved_players, list):
            return defaultdict(lambda: {"name": "", "bases": None})
        guild_bases = {
            guild.get("group_id"): guild.get("base_count")
            for guild in saved_guilds
            if isinstance(guild, dict) and guild.get("group_id")
        }
        guild_names = {
            guild.get("group_id"): guild.get("guild_name", "")
            for guild in saved_guilds
            if isinstance(guild, dict) and guild.get("group_id")
        }
        result = defaultdict(lambda: {"name": "", "bases": None})
        for saved_player in saved_players:
            if not isinstance(saved_player, dict):
                continue
            name = str(saved_player.get("player_name", "")).strip().casefold()
            guild_id = saved_player.get("guild_id")
            if not name or not isinstance(guild_id, str) or not guild_id:
                continue
            result[name] = {
                "name": guild_names.get(guild_id, ""),
                "bases": guild_bases.get(guild_id),
            }
        return result
