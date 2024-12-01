from datetime import datetime, timezone

def ts_to_rfc3339(ts_str):
    unix_timestamp = float(ts_str)
    datetime_obj = datetime.fromtimestamp(unix_timestamp, tz=timezone.utc)
    return datetime_obj.isoformat()
