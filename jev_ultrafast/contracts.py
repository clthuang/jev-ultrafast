"""Small shared contracts for explicitly authorized browser operations and terminal stops."""

SUPPORTED_OPERATIONS = frozenset({"CLICK", "TYPE_TEXT", "SELECT", "SCROLL_UP", "SCROLL_DOWN", "WAIT"})
TERMINAL_STATES = frozenset({"done", "blocked", "stopped"})
DIAGNOSTIC_CHARACTERS = 160


class RunStopped(ValueError):
    """A terminal executor refusal; never a retryable page freshness failure."""

    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def token_usage(calls, field):
    """Known token subtotal and unknown call count; an absent provider field is never a measured zero."""
    total, unknown = 0, 0
    for call in calls:
        usage = call.get("usage")
        value = usage.get(field) if isinstance(usage, dict) else None
        if type(value) is int and value >= 0:
            total += value
        else:
            unknown += 1
    return total, unknown


def operation_diagnostic(decision, reason, actual=None):
    """Small inert strings only: malformed response objects never become executable state or unbounded logs."""
    fields = decision if isinstance(decision, dict) else {}

    def shown(value):
        if value is None:
            return None
        return value[:DIAGNOSTIC_CHARACTERS] if isinstance(value, str) else f"<invalid {type(value).__name__}>"

    return {
        "claimed_operation": shown(fields.get("operation")), "actual_operation": shown(actual),
        "choice": shown(fields.get("choice")), "target": shown(fields.get("target")),
        "reason": reason[:DIAGNOSTIC_CHARACTERS],
    }


class InvalidDecision(ValueError):
    """The provider returned unusable selected-operation metadata; transport failures are a separate path."""

    def __init__(self, decision):
        message = "Invalid TypeSafe response; no action executed."
        self.diagnostic = operation_diagnostic(decision, message)
        super().__init__(message)


def validate_allowed_operations(value):
    """Validate before setup/reset. There is deliberately no permissive default."""
    if (not isinstance(value, list) or any(not isinstance(item, str) for item in value)
            or len(set(value)) != len(value) or not set(value) <= SUPPORTED_OPERATIONS):
        raise ValueError(
            "Supply allowed_operations as an explicit list of unique CLICK, TYPE_TEXT, SELECT, "
            "SCROLL_UP, SCROLL_DOWN or WAIT names; [] allows observation and terminal answers only."
        )
    return frozenset(value)


def validate_goal(value):
    """Normalize a goal before a caller changes any existing run or browser."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Supply a nonempty task")
    return value.strip()


def operation_for(action):
    """Derive authority from code-owned observed actions, never model metadata."""
    operation = {"click": "CLICK", "fill": "TYPE_TEXT", "select": "SELECT", "wait": "WAIT"}.get(action["kind"])
    if operation is not None:
        return operation
    if action["kind"] == "scroll":
        operation = {"scroll_up": "SCROLL_UP", "scroll_down": "SCROLL_DOWN"}.get(action["id"])
        if operation and ((action["delta"] > 0) == (operation == "SCROLL_DOWN")) and action["delta"] != 0:
            return operation
    raise ValueError("Unsupported observed operation")
