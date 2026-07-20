from django.urls import path

from dashboard import views


urlpatterns = [
    path("", views.home, name="home"),
    path("healthz/", views.health, name="health"),
    path("api/v1/snapshot", views.snapshot, name="snapshot"),
    path("api/v1/history", views.history, name="history"),
    path("api/v1/players", views.players, name="players"),
    path("api/v1/player/<str:public_id>/trail", views.player_trail, name="player-trail"),
]
