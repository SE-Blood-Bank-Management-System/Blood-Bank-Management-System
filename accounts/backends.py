from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.db.models import Q


class EmailOrUsernameModelBackend(ModelBackend):
    """
    Authentication backend allowing users to log in using either their username
    or their registered email address.
    SRS References: 4.1 (BBMS-F-004), 4.13 (BBMS-F-041), 5.1.2 (BBMS-SR-001).
    """
    def authenticate(self, request, username=None, password=None, **kwargs):
        user_model = get_user_model()
        if username is None:
            username = kwargs.get(user_model.USERNAME_FIELD)
        if not username or not password:
            return None

        clean_username = username.strip()
        try:
            user = user_model.objects.filter(
                Q(username__iexact=clean_username) | Q(email__iexact=clean_username)
            ).first()
        except Exception:
            return None

        if user and user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
