import json
import secrets

from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .services import IngestError, process_records


def _error(message, status):
    return JsonResponse({"error": message}, status=status)


@csrf_exempt
@require_POST
def ingest(request):
    expected = settings.ZABBIX_CONNECTOR_TOKEN
    if not expected:
        return _error("connector token is not configured", 503)

    authorization = request.headers.get("Authorization", "")
    provided = authorization[7:] if authorization.startswith("Bearer ") else ""
    if not provided or not secrets.compare_digest(provided, expected):
        return _error("unauthorized", 401)

    content_type = request.content_type.lower()
    if content_type not in {"application/x-ndjson", "application/ndjson"}:
        return _error("Content-Type must be application/x-ndjson", 415)

    content_length = request.META.get("CONTENT_LENGTH")
    try:
        if content_length and int(content_length) > settings.INGEST_MAX_BYTES:
            return _error("request body is too large", 413)
    except ValueError:
        return _error("invalid Content-Length", 400)

    body = request.body
    if len(body) > settings.INGEST_MAX_BYTES:
        return _error("request body is too large", 413)

    records = []
    parse_errors = []
    line_number = 0
    try:
        lines = body.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        return _error(f"invalid UTF-8: {exc}", 422)

    for line_number, line in enumerate(lines, start=1):
        try:
            if not line.strip():
                continue
            if len(records) >= 1000:
                return _error("batch contains more than 1000 records", 413)
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError("record is not an object")
            records.append(value)
        except (json.JSONDecodeError, ValueError) as exc:
            parse_errors.append(f"line {line_number}: {exc}")

    if not records:
        message = parse_errors[0] if parse_errors else "empty NDJSON batch"
        return _error(message, 422)

    result = process_records(records)
    result["rejected"] += len(parse_errors)
    result["errors"] = (result["errors"] + parse_errors)[:10]
    if result["accepted"] == 0 and result["ignored"] == 0 and result["rejected"]:
        return JsonResponse({"error": result["errors"][0], **result}, status=422)

    return JsonResponse({"response": "success", **result})
