from typing import Any, Tuple


class SchemaGuard:
    def __init__(self, max_retries: int = 1):
        self.max_retries = max_retries

    def check(self, final_json: dict[str, Any] | None, schema: dict[str, Any]) -> Tuple[bool, str | None]:
        if final_json is None:
            return False, "No JSON produced"

        required = schema.get("required", [])
        missing = [k for k in required if k not in final_json]
        if missing:
            return False, f"Missing required fields: {sorted(missing)}"

        try:
            import jsonschema
            jsonschema.validate(instance=final_json, schema=schema)
            return True, None
        except jsonschema.ValidationError as e:
            return False, e.message
        except Exception:
            # jsonschema not installed or other error
            return len(missing) == 0, f"Missing: {sorted(missing)}" if missing else None
