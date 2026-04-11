import logging
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal
from django.utils import timezone
from django.db.models import Count
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from api.models import LocationLog
from api.Serializers.location_log_serializer import LocationLogSerializer
from drf_spectacular.utils import extend_schema, OpenApiParameter

logger = logging.getLogger('api')


def _grid_cell(lat: float, lng: float, cell_size_degrees: float = 0.005) -> tuple:
    """
    Convert lat/lng to a grid cell.
    cell_size_degrees ~0.005 = ~500m radius (at equator).
    """
    cell_lat = int(lat / cell_size_degrees)
    cell_lng = int(lng / cell_size_degrees)
    return (cell_lat, cell_lng)


def _cell_center(cell: tuple, cell_size_degrees: float = 0.005) -> tuple:
    """Get the center coordinates of a grid cell."""
    center_lat = (cell[0] + 0.5) * cell_size_degrees
    center_lng = (cell[1] + 0.5) * cell_size_degrees
    return (center_lat, center_lng)


@extend_schema(tags=['LocationLogs'])
class LocationLogViewSet(viewsets.ModelViewSet):
    """ViewSet estándar para LocationLogs (Heat Map data)."""
    serializer_class = LocationLogSerializer

    def get_queryset(self):
        """Return location logs linked to the user's blitzes."""
        return LocationLog.objects.filter(
            blitz__group__groupmembership__user=self.request.user
        ).distinct()

    @extend_schema(
        tags=['HeatMap'],
        summary='Get heat map data with trending activities',
        description='Returns aggregated Blitz start locations grouped into grid cells. '
                    'Each cell shows the trending activity (most common) for that zone. '
                    'Only cells with >= min_count Blitzes are returned.',
        parameters=[
            OpenApiParameter(
                name='hours',
                type=int,
                description='Number of hours to look back (default: 24)',
                required=False,
            ),
            OpenApiParameter(
                name='min_count',
                type=int,
                description='Minimum Blitz count to include a cell (default: 3)',
                required=False,
            ),
            OpenApiParameter(
                name='cell_size',
                type=float,
                description='Grid cell size in degrees (default: 0.005 = ~500m)',
                required=False,
            ),
        ],
    )
    @action(detail=False, methods=['get'], url_path='heatmap')
    def heatmap(self, request):
        """
        Aggregate blitz_start locations into grid cells for heat map visualization.
        Returns cells with count >= min_count (default 3).
        Each cell includes the trending activity (most popular in that zone).
        """
        # Parse parameters
        hours = int(request.query_params.get('hours', 24))
        min_count = int(request.query_params.get('min_count', 3))
        cell_size = float(request.query_params.get('cell_size', 0.005))

        # Clamp values for safety
        hours = max(1, min(hours, 720))  # 1 hour to 30 days
        min_count = max(1, min(min_count, 100))
        cell_size = max(0.001, min(cell_size, 0.1))  # ~100m to ~10km

        # Get blitz_start events from the last N hours, join with Blitz for activity_type
        cutoff = timezone.now() - timedelta(hours=hours)
        logs = LocationLog.objects.filter(
            event_type__startswith='blitz_start',
            created_at__gte=cutoff,
        ).select_related('blitz').values('latitude', 'longitude', 'blitz__activity_type')

        # Group into grid cells and track activities
        cells = defaultdict(int)
        cell_activities = defaultdict(lambda: defaultdict(int))  # cell -> activity -> count

        for log in logs:
            lat = float(log['latitude'])
            lng = float(log['longitude'])
            cell = _grid_cell(lat, lng, cell_size)
            cells[cell] += 1

            # Track activity for this cell
            activity = log.get('blitz__activity_type') or ''
            if activity:
                cell_activities[cell][activity] += 1

        # Filter cells with >= min_count and calculate intensity
        result = []
        max_count = max(cells.values()) if cells else 1

        # Track global activity counts for trending
        global_activities = defaultdict(int)

        for cell, count in cells.items():
            if count >= min_count:
                center = _cell_center(cell, cell_size)
                # Intensity from 0.3 (min) to 1.0 (max)
                intensity = 0.3 + (0.7 * (count / max_count))

                # Find trending activity for this cell
                activities = cell_activities.get(cell, {})
                trending_activity = None
                if activities:
                    trending_activity = max(activities.keys(), key=lambda a: activities[a])
                    # Add to global count
                    for act, act_count in activities.items():
                        global_activities[act] += act_count

                result.append({
                    'lat': round(center[0], 6),
                    'lng': round(center[1], 6),
                    'count': count,
                    'intensity': round(intensity, 2),
                    'radius_m': int(cell_size * 111000 / 2),
                    'trending_activity': trending_activity,
                    'activities': dict(activities) if activities else {},
                })

        # Sort by count descending
        result.sort(key=lambda x: x['count'], reverse=True)

        # Get top 5 global trending activities
        trending = sorted(global_activities.items(), key=lambda x: -x[1])[:5]

        return Response({
            'cells': result,
            'total_blitzes': sum(c['count'] for c in result),
            'hot_zones': len(result),
            'hours_back': hours,
            'min_count': min_count,
            'trending_activities': [{'activity': a, 'count': c} for a, c in trending],
        })