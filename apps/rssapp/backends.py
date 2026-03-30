from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend

User = get_user_model()


class EmailBackend(ModelBackend):
    """Authenticate with email address instead of username."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        # Allow 'email' kwarg as well as 'username' (Django's default field name)
        email = kwargs.get("email", username)
        if email is None or password is None:
            return None
        try:
            user = User.objects.get(email__iexact=email)
        except (User.DoesNotExist, User.MultipleObjectsReturned):
            # Run the default password hasher to mitigate timing attacks
            User().set_password(password)
            return None
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
