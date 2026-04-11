from rest_framework import serializers
from api.models import User, Profile
from django.db.models import Q


class UserSerializer(serializers.HyperlinkedModelSerializer):
    """
    Serializer para User con validaciones de seguridad.

    🔒 PROTECCIONES:
    - firebase_uid es read_only (set por Firebase)
    - is_staff e is_superuser NUNCA editables vía API
    - email: validar unicidad y no permitir duplicados
    - role: solo ADMIN puede asignar; usuario regular NO puede cambiar el suyo
    """

    bio = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=500,
        default='',
    )
    interests = serializers.ListField(
        child=serializers.CharField(max_length=50),
        required=False,
        default=list,
    )
    age = serializers.IntegerField(required=False, allow_null=True, min_value=13, max_value=120)
    gender = serializers.CharField(required=False, allow_blank=True, max_length=20, default='')
    default_location = serializers.JSONField(required=False, default=dict)
    is_premium = serializers.BooleanField(read_only=True)
    plan_features = serializers.SerializerMethodField(read_only=True)
    cancel_at_period_end = serializers.SerializerMethodField(read_only=True)
    subscription_end_date = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = User
        fields = [
            'url', 'id', 'first_name', 'last_name', 'email', 'phone',
            'firebase_uid', 'profile_photo', 'is_verified', 'is_active',
            'role', 'preferences', 'total_memories',
            'bio', 'interests', 'age', 'gender', 'default_location',
            'is_premium', 'plan_features',
            'cancel_at_period_end', 'subscription_end_date',
            'created_at', 'updated_at'
        ]
        read_only_fields = [
            'firebase_uid',      # 🔒 No editable (set por Firebase)
            'is_staff',          # 🔒 NUNCA editable vía API
            'is_superuser',      # 🔒 NUNCA editable vía API
            'total_memories',    # Computed property
            'is_premium',        # Computed billing property
            'plan_features',     # Computed from plan
            'cancel_at_period_end',  # Subscription cancellation flag
            'subscription_end_date', # Subscription end date
            'created_at',
            'updated_at'
        ]

    def get_bio(self, obj):
        try:
            return obj.profile.bio or ''
        except Profile.DoesNotExist:
            return ''

    def to_representation(self, instance):
        """Include profile fields in read responses."""
        data = super().to_representation(instance)
        try:
            profile = instance.profile
            data['bio'] = profile.bio or ''
            data['interests'] = profile.interests or []
            data['age'] = profile.age
            data['gender'] = profile.gender or ''
            data['default_location'] = profile.default_location or {}
        except Profile.DoesNotExist:
            data['bio'] = ''
            data['interests'] = []
            data['age'] = None
            data['gender'] = ''
            data['default_location'] = {}
        return data

    # Hardcoded Free defaults for users without any subscription
    FREE_DEFAULTS = {
        'max_groups': 3,
        'max_blitz_per_week': 3,
        'max_swipes_per_blitz': 10,
        'max_solo_connections': 5,
        'advanced_filters': False,
        'voice_chat': False,
        'full_heat_map': False,
        'detailed_stats': False,
        'blur_notifications': True,
    }

    BOOL_FEATURES = {
        'advanced_filters', 'voice_chat', 'full_heat_map',
        'detailed_stats', 'blur_notifications',
    }
    INT_FEATURES = {'max_groups', 'max_blitz_per_week', 'max_swipes_per_blitz', 'max_solo_connections'}

    def get_plan_features(self, obj):
        if not obj.current_plan:
            return self.FREE_DEFAULTS.copy()

        result = {}
        for key in self.FREE_DEFAULTS:
            if key in self.BOOL_FEATURES:
                result[key] = obj.has_feature(key)
            else:
                result[key] = obj.get_feature_limit(key)
        return result

    def get_cancel_at_period_end(self, obj):
        sub = obj.active_subscription
        if sub:
            return sub.cancel_at_period_end
        return False

    def get_subscription_end_date(self, obj):
        sub = obj.active_subscription
        if sub and sub.current_period_end:
            return sub.current_period_end.isoformat()
        return None

    def validate_email(self, value):
        """
        🔒 Verificar que el email no esté en uso por otro usuario.
        """
        # Si estamos actualizando, permitir el email actual
        if self.instance and self.instance.email == value:
            return value
        # Verificar que no esté en uso por otro usuario
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError(
                "Este email ya está registrado en el sistema"
            )

        return value

    def validate_phone(self, value):
        """
        🔒 Validar formato de teléfono (solo números, +, -).
        """
        if value and not all(c.isdigit() or c in ['+', '-', ' '] for c in value):
            raise serializers.ValidationError(
                "El teléfono debe contener solo números, +, - o espacios"
            )

        return value

    def validate_role(self, value):
        """
        🔒 Solo ADMIN puede asignar/cambiar roles.
        Un usuario regular NO puede cambiar su propio rol.
        """
        request = self.context.get('request')

        if not request:
            raise serializers.ValidationError("Contexto de request faltante")

        current_user = request.user
        instance = self.instance

        # Caso: Actualizando rol de otro usuario
        if instance and instance.id != current_user.id:
            # Solo ADMIN puede cambiar rol de otros
            if current_user.role != User.Roles.ADMIN:
                raise serializers.ValidationError(
                    "Solo ADMIN puede cambiar roles de otros usuarios"
                )
        # Caso: Editando rol de sí mismo
        if instance and instance.id == current_user.id:
            # Usuario regular NO puede cambiar su propio rol
            if current_user.role != User.Roles.ADMIN:
                raise serializers.ValidationError(
                    "No puedes cambiar tu propio rol"
                )
        # Solo ADMIN puede asignar ADMIN
        if value == User.Roles.ADMIN:
            if current_user.role != User.Roles.ADMIN:
                raise serializers.ValidationError(
                    "Solo ADMIN puede crear/asignar otros ADMIN"
                )

        return value

    def create(self, validated_data):
        """
        🔒 Asegurar que nuevos usuarios siempre sean REGULAR.

        NOTA: Los usuarios se crean principalmente vía Firebase auth,
        pero si se crea uno aquí, forzar REGULAR role.
        """
        # Profile fields belong on Profile, not User
        for key in ('bio', 'interests', 'age', 'gender', 'default_location'):
            validated_data.pop(key, None)
        validated_data['is_staff'] = False
        validated_data['is_superuser'] = False
        validated_data['role'] = validated_data.get('role', User.Roles.REGULAR)

        return super().create(validated_data)

    def update(self, instance, validated_data):
        """Handle nested profile field updates."""
        profile_fields = {}
        for key in ('bio', 'interests', 'age', 'gender', 'default_location'):
            val = validated_data.pop(key, None)
            if val is not None:
                profile_fields[key] = val

        instance = super().update(instance, validated_data)

        if profile_fields:
            profile, _ = Profile.objects.get_or_create(user=instance)
            for key, val in profile_fields.items():
                setattr(profile, key, val)
            profile.save(update_fields=list(profile_fields.keys()))

        return instance
