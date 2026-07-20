from django.contrib.auth.tokens import PasswordResetTokenGenerator


class EmailVerificationTokenGenerator(PasswordResetTokenGenerator):
    def _make_hash_value(self, user, timestamp):
        profile = getattr(user, "site_profile", None)
        verified = profile.email_verified if profile else False
        return f"{user.pk}{timestamp}{user.email}{verified}"


email_verification_token = EmailVerificationTokenGenerator()
