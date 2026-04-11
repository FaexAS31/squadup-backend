# SquadUp Backend

REST API for SquadUp, a social app where friend groups join time-limited "Blitz" sessions to discover other groups nearby and match for real-life meetups.

Built with Django 6 and Django REST Framework, served via Daphne (ASGI) for WebSocket support alongside regular HTTP endpoints.

This is the public version of the project, adjusted for open sharing. Credentials and environment-specific config are excluded, and the CI/CD workflow builds and pushes the Docker image to GHCR but does not deploy to a server since those secrets are private.

The Docker Compose setup and monitoring config live in [`infra/`](./infra/).

## What it does

Groups of friends activate a Blitz session, browse other active groups, and swipe like or skip. When two groups both like each other a match is created and a temporary group chat opens. There is also a Solo Mode where individual users can connect directly with each other.

The backend handles all of this plus Firebase JWT authentication, push notifications via FCM, subscription billing via Stripe, real-time coordination over WebSockets, and a heat map of activity by zone.

## Tech stack

- **Django 6.0.1** + Django REST Framework
- **PostgreSQL 16** as the main database
- **Redis 7** as the Django Channels layer for WebSocket pub/sub
- **Daphne** as the ASGI server
- **Firebase Admin SDK** for JWT auth and push notifications (FCM)
- **Stripe** for subscription billing and Checkout sessions
- **drf-spectacular** for auto-generated OpenAPI docs (Swagger + ReDoc)
- **django-prometheus** + Grafana + Loki for metrics and log aggregation
- All services orchestrated with **Docker Compose**

## Project structure

```
backend/
  Dockerfile
  scripts/
    install.sh        # System-level deps for the Ubuntu base image
    entrypoint.sh     # Container startup (migrations + server)
  src/
    requirements.txt
    core/
      manage.py
      core/           # Django project settings, root URLs, ASGI config
      api/
        models.py         # All domain models (~35) in one file
        Viewsets/         # One file per ViewSet, auto-discovered
        Serializers/      # One file per Serializer
        consumers.py      # Django Channels WebSocket consumers
        management/       # Custom management commands
      utils/
        router_utils.py       # Auto-registers ViewSets to DRF router
        logging_middleware.py # Logs every request/response
        stripe_service.py     # Stripe Checkout helpers
        fcm_service.py        # Firebase Cloud Messaging
        billing_helpers.py    # Subscription and plan utilities
infra/
  compose.yaml        # Multi-environment Docker Compose (prod + staging)
  nginx/              # Nginx reverse proxy config
  prometheus/         # Prometheus scrape config
  grafana/            # Grafana datasources and dashboards (auto-provisioned)
  loki/               # Loki log aggregation config
```

### Auto-routing

ViewSets are automatically discovered and registered. `utils/router_utils.py` scans `api/Viewsets/` for any class ending in `ViewSet` and registers it on the DRF router with a pluralized URL. Adding a new endpoint only requires creating the ViewSet file, no URL config changes needed.

## Running locally

Requires Docker and Docker Compose.

```bash
# Copy the example env and fill in your values
cp .env.example .env

# Place your Firebase service account JSON at the path set in FIREBASE_SERVICE_ACCOUNT_PATH

# Start everything
cd infra && docker compose up -d

# Run migrations
docker exec -it <backend_container> python3 manage.py migrate

# Create a superuser
docker exec -it <backend_container> python3 manage.py createsuperuser
```

Once running:

| Service | URL |
|---------|-----|
| API root | http://localhost:8000/api/ |
| Swagger UI | http://localhost:8000/api/schema/swagger-ui/ |
| ReDoc | http://localhost:8000/api/schema/redoc/ |
| Django Admin | http://localhost:8000/admin |
| Grafana | http://localhost:3000 |
| Prometheus | http://localhost:9090 |

## Authentication

All endpoints require a Firebase ID token passed as `Authorization: Bearer <token>`. The backend verifies it with Firebase Admin SDK and auto-creates the user record on first request.

## Main endpoints

```
# Users
GET/POST    /api/users/
GET/PATCH   /api/users/me/
GET         /api/users/search/
GET         /api/users/discoverable/          # Scored recommendations for Solo Mode

# Profiles and photos
GET/PATCH   /api/profiles/
POST        /api/profilephotos/

# Groups and friends
GET/POST    /api/groups/
POST        /api/groups/quick_duo/            # Create duo group + auto-start blitz
GET/POST    /api/groupmemberships/
GET/POST    /api/friendships/
POST        /api/friendships/solo_like/       # Solo like -> { is_match, friendship_id }

# Blitz sessions
GET/POST    /api/blitzes/
GET/POST    /api/blitzinteractions/           # Swipe actions (like/skip)
GET/POST    /api/blitzvotes/                  # Democratic voting per interaction

# Matches and chat
GET/POST    /api/matches/
GET/POST    /api/chats/
GET/POST    /api/messages/

# Solo Mode coordination
GET         /api/solomatches/
POST        /api/solomatches/swipe/
POST        /api/solomatches/{id}/cancel/
GET         /api/solocoordinations/{id}/
POST        /api/solocoordinations/{id}/update_preferences/
POST        /api/solocoordinations/{id}/ready/
POST        /api/solocoordinations/{id}/start/

# Real-time
WS          /ws/coordination/{match_id}/

# Billing
POST        /api/subscriptions/create-checkout/
POST        /api/stripe/webhook/

# Other
GET/POST    /api/meetupplans/
GET/POST    /api/memories/
GET/POST    /api/notifications/
GET/POST    /api/locationlogs/
GET/POST    /api/reports/
```

## Domain models

**Social/Matching:** User, Profile, Friendship, Group, GroupMembership, Blitz, BlitzInteraction, BlitzVote, Match, MatchActivity, Chat, Message, Notification, Report, SoloMatch, SoloCoordination

**Billing:** Plan, PlanFeature, Subscription, PaymentMethod, Invoice, Payment, Coupon, Discount

**Location:** LocationLog, ZoneStats

**Devices:** DeviceToken, ProfilePhoto

## WebSockets

The Solo Mode coordination flow happens over a WebSocket at `/ws/coordination/{match_id}/` powered by Django Channels with a Redis channel layer. The ASGI config in `core/asgi.py` routes HTTP to Django and WebSocket traffic to the Channels consumers.

## Monitoring

Prometheus, Loki, and Grafana are included in the infra. The backend exposes `/metrics` via `django-prometheus`. Grafana datasources and dashboards are auto-provisioned from `infra/grafana/provisioning/`.

## Environment variables

Copy `.env.example` to `.env` and fill in the values.

| Variable | Description |
|----------|-------------|
| `SECRET_KEY` | Django secret key |
| `DB_USER`, `DB_PASSWORD`, `DB_NAME` | PostgreSQL credentials |
| `FIREBASE_SERVICE_ACCOUNT_PATH` | Path to the Firebase Admin SDK JSON file |
| `STRIPE_SECRET_KEY` | Stripe API secret key |
| `STRIPE_WEBHOOK_SECRET` | Stripe webhook signing secret |

## Management commands

```bash
# Django shell
docker exec -it <backend_container> python3 manage.py shell

# Expire stale Solo matches (run on a cron every 5 minutes)
docker exec -it <backend_container> python3 manage.py expire_solo_matches

# Seed subscription plans
docker exec -it <backend_container> python3 manage.py seed_plans

# Migrations
docker exec -it <backend_container> python3 manage.py makemigrations
docker exec -it <backend_container> python3 manage.py migrate
```
