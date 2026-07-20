from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend


class EmailOrUsernameBackend(ModelBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        if not username or password is None:
            return None
        user_model = get_user_model()
        try:
            lookup = (
                {"email__iexact": username}
                if "@" in username
                else {"username__iexact": username}
            )
            user = user_model.objects.get(**lookup)
        except (user_model.DoesNotExist, user_model.MultipleObjectsReturned):
            user_model().set_password(password)
            return None
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
