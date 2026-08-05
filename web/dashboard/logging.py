import logging
import re


SENSITIVE_PATH_PATTERN = re.compile(
    r"/accounts/(?P<kind>verify|reset)/[^/\s?]+/[^/\s?]+/"
)


def _redact_sensitive_paths(value):
    if not isinstance(value, str):
        return value
    return SENSITIVE_PATH_PATTERN.sub(
        lambda match: f"/accounts/{match.group('kind')}/[redacted]/[redacted]/",
        value,
    )


class RedactSensitivePathsFilter(logging.Filter):
    def filter(self, record):
        record.msg = _redact_sensitive_paths(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(_redact_sensitive_paths(value) for value in record.args)
        elif isinstance(record.args, dict):
            record.args = {
                key: _redact_sensitive_paths(value)
                for key, value in record.args.items()
            }
        return True
