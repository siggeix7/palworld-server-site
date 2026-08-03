from collections import defaultdict
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Avg, Max, Min
from django.template.loader import render_to_string
from django.utils import timezone

from dashboard.emails import send_weekly_report_email
from dashboard.models import LatestDataset, MetricSample, Player, PlayerSession
from dashboard.views import _uptime_pct


class Command(BaseCommand):
    help = "Send the weekly Palworld server report to the site administrators"

    def handle(self, *args, **options):
        now = timezone.now()
        since = now - timedelta(days=7)

        uptime_24h, _ = _uptime_pct(timedelta(hours=24), now)
        uptime_7d, _ = _uptime_pct(timedelta(days=7), now)
        aggregates = MetricSample.objects.filter(
            source_clock__gte=since, source_clock__lte=now
        ).aggregate(
            average_players=Avg("current_players"),
            peak_players=Max("current_players"),
            average_fps=Avg("server_fps_average"),
            minimum_fps=Min("server_fps"),
        )

        metrics = LatestDataset.objects.filter(key="metrics").first()
        metrics_payload = metrics.payload if metrics else {}
        world_days = metrics_payload.get("days")
        base_camps = metrics_payload.get("basecampnum")

        sessions = list(
            PlayerSession.objects.filter(
                started_at__lt=now,
                ended_at__gt=since,
            ).select_related("player")
        ) + list(
            PlayerSession.objects.filter(
                started_at__lt=now,
                ended_at__isnull=True,
            ).select_related("player")
        )
        totals = defaultdict(int)
        for session in sessions:
            stale_end = session.last_seen + timedelta(seconds=settings.DATA_STALE_SECONDS)
            end = session.ended_at or min(now, stale_end)
            start = max(session.started_at, since)
            if end > start:
                totals[session.player_id] += int((end - start).total_seconds())

        player_names = dict(
            Player.objects.filter(id__in=list(totals)).values_list("id", "name")
        )
        top_players = [
            {"name": player_names.get(player_id, "?"), "minutes": seconds // 60}
            for player_id, seconds in sorted(totals.items(), key=lambda item: -item[1])[:5]
        ]

        new_players = list(
            Player.objects.filter(first_seen__gte=since)
            .order_by("first_seen")
            .values_list("name", flat=True)
        )
        session_count = PlayerSession.objects.filter(started_at__gte=since).count()

        context = {
            "since_label": since.strftime("%d/%m/%Y"),
            "until_label": now.strftime("%d/%m/%Y"),
            "uptime_24h": round(uptime_24h, 1),
            "uptime_7d": round(uptime_7d, 1),
            "average_players": round(aggregates["average_players"] or 0, 1),
            "peak_players": aggregates["peak_players"] or 0,
            "average_fps": round(aggregates["average_fps"] or 0, 1),
            "minimum_fps": aggregates["minimum_fps"],
            "world_days": world_days,
            "base_camps": base_camps,
            "session_count": session_count,
            "new_player_count": len(new_players),
            "new_players": new_players[:5],
            "top_players": top_players,
            "public_site_url": settings.PUBLIC_SITE_URL,
        }
        message = render_to_string("dashboard/emails/weekly_report.txt", context)
        sent = send_weekly_report_email(
            f"Report settimanale Palworld · {context['since_label']} → {context['until_label']}",
            message,
        )
        if not sent:
            raise CommandError("no administrator recipients configured")
        self.stdout.write(f"Weekly report sent to {sent} recipient(s)")
