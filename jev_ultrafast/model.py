"""TypeSafe makes choices; an optional small OpenAI-compatible model writes field values."""

import json
import math
import os
import time

import httpx

from .contracts import InvalidDecision
from .questions import COMMIT, COMMIT_CRITERIA, NEXT_ACTION, TARGET, TEXT_VALUE

CLIENT = httpx.Client(http2=True, timeout=25)


def post_json(url, key, body, *, check_stop=None, remaining_budget=None):
    for attempt in range(3):
        if check_stop:
            check_stop()
        options = {"timeout": min(25, remaining_budget())} if remaining_budget else {}
        try:
            response = CLIENT.post(url, json=body, headers={"Authorization": f"Bearer {key}"}, **options)
        except httpx.HTTPError:
            if check_stop:
                check_stop()
            raise RuntimeError("Model connection failed; no action executed.") from None
        if response.status_code in {429, 529, 503} and attempt < 2:
            if check_stop:
                check_stop()
            delay = 0.5 * 2**attempt
            time.sleep(min(delay, remaining_budget()) if remaining_budget else delay)
            continue
        if response.is_error:
            if check_stop:
                check_stop()
            raise RuntimeError(f"Model provider returned HTTP {response.status_code}; no action executed.")
        # The caller records completed-response usage before applying its post-response stop check.
        return response.json()
    raise RuntimeError("Model unavailable")


def validate_choice(answer, ids):
    try:
        probabilities = answer["probabilities"]
        numbers = [*probabilities.values(), answer["confidence"]]
        valid = (
            answer["choice"] in ids
            and set(probabilities) == set(ids)
            and all(type(n) in (int, float) and math.isfinite(n) and 0 <= n <= 1 for n in numbers)
            and abs(sum(probabilities.values()) - 1) < 0.02
            and probabilities[answer["choice"]] >= max(probabilities.values()) - 1e-6
        )
    except (KeyError, TypeError, ValueError):
        valid = False
    if not valid:
        raise ValueError("Invalid TypeSafe response; no action executed.")
    return answer


def validate_noul(answer):
    try:
        value = answer["noul"]
        valid = type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 1
    except (KeyError, TypeError):
        valid = False
    if not valid:
        raise ValueError("Invalid TypeSafe response; no action executed.")
    return value


def commit_question(target):
    """Question id for one target's commit judgment. SELECT keys such as 5:2 become commit_5_2."""
    return "commit_" + target.replace(":", "_")


def action_space(actions, allowed_operations=None, *, evidence=()):
    """One index per observed element; each operation has its own valid target choices."""
    elements, indices, targets, controls = [], {}, {}, {}
    operations = {"click": "CLICK", "fill": "TYPE_TEXT", "select": "SELECT"}
    for action in actions:
        kind = action["kind"]
        if kind not in operations:
            controls[action["id"].upper()] = action
            continue
        node = action["node"]
        if node not in indices:
            index = str(len(elements) + 1)
            indices[node] = index
            element = {k: action[k] for k in ("role", "value", "checked", "selected", "expanded") if k in action}
            element.update(index=index, node=node, label=action["label"].split(" → ")[0], operations=[])
            if "rect" in action:
                element["rect"] = action["rect"]
            if kind == "select":
                element["value"] = action.get("current_value", "")
                element["options"] = []
            elements.append(element)
        index = indices[node]
        operation = operations[kind]
        group = targets.setdefault(operation, {})
        element = elements[int(index) - 1]
        if operation not in element["operations"]:
            element["operations"].append(operation)
        target = index
        if kind == "select":
            target = f"{index}:{len(element['options']) + 1}"
            element["options"].append({"index": target, "label": action["label"], "value": action["value"]})
        group[target] = action
    if allowed_operations is not None:
        targets = {operation: values for operation, values in targets.items() if operation in allowed_operations}
        controls = {operation: action for operation, action in controls.items() if operation in allowed_operations}
        for element in elements:
            element["operations"] = [
                operation for operation in element["operations"] if operation in allowed_operations
            ]
    # Observation-only controls never enter target or commit heads and cannot renumber actionable elements.
    for observed in evidence:
        elements.append({**observed, "index": str(len(elements) + 1), "operations": []})
    return elements, targets, controls


def choose(state, goal, history, allowed_operations, *, check_stop=None, remaining_budget=None, on_response=None):
    key = os.environ.get("TYPESAFE_API_KEY")
    if not key:
        raise ValueError("TYPESAFE_API_KEY is not set; add it to .env. No action executed.")
    elements, targets, controls = action_space(state["actions"], allowed_operations, evidence=state.get("evidence", ()))
    labels = {
        "CLICK": "Click an element, button, menu option, autocomplete suggestion, or calendar day.",
        "TYPE_TEXT": "Enter or replace text in an editable field. A small LLM will supply the value from the goal.",
        "SELECT": "Select an observed dropdown value.",
    }
    operations = {key: labels[key] for key in targets}
    operations.update({key: value["label"] for key, value in controls.items()})
    operations.update(DONE="Every requirement is visibly satisfied.", BLOCKED="No supported operation can progress.")
    questions = {
        "operation": {"type": "choice", "criteria": operations, "instructions": {"goal": goal, "rules": NEXT_ACTION}}
    }
    for operation, candidates in targets.items():
        questions[operation.lower() + "_target"] = {
            "type": "choice",
            "criteria": {
                index: {
                    "element": f"[{index}] {a['label']}",
                    "current_value": a.get("current_value", a.get("value", "")),
                    **{k: a[k] for k in ("role", "checked", "selected", "expanded") if k in a},
                }
                for index, a in candidates.items()
            },
            "instructions": {"goal": goal, "operation": operation, "rules": [NEXT_ACTION, TARGET]},
        }
    # Speculative commit judgments in the same request. Only the chosen target's answer is consumed.
    for kind in ("CLICK", "SELECT"):
        for target, action in targets.get(kind, {}).items():
            questions[commit_question(target)] = {
                "type": "noul",
                "instructions": COMMIT.format(element=f"[{target}] {action['label']}"),
                "criteria": COMMIT_CRITERIA,
            }
    body = {
        "model": os.environ.get("TYPESAFE_MODEL", "jev-latest"),
        "state": {
            "page": {k: state[k] for k in ("url", "title", "text")},
            "elements": [{k: v for k, v in element.items() if k not in {"node", "rect"}} for element in elements],
            "recent_actions": [
                {k: h.get(k) for k in ("action", "kind", "text", "page_changed")} for h in history[-10:]
            ],
        },
        "questions": questions,
    }
    started = time.perf_counter()
    control = {"check_stop": check_stop, "remaining_budget": remaining_budget} if check_stop else {}
    result = post_json("https://api.typesafe.ai/v1/systemone", key, body, **control)
    response_metadata = {
        "model": (result["model"] if isinstance(result, dict) and isinstance(result.get("model"), str)
                  else body["model"]),
        "usage": (result["usage"] if isinstance(result, dict) and isinstance(result.get("usage"), dict) else {}),
        "latency_ms": round((time.perf_counter() - started) * 1000),
    }
    if on_response:
        on_response(response_metadata)
    if check_stop:
        check_stop()
    # Only response-shape validation is caught here. Credentials, HTTP and provider transport errors above retain
    # their original behavior; an unusable chosen operation is a terminal refusal in the Agent.
    metadata = {}
    try:
        answers = result["answers"]
        raw_operation = answers.get("operation", {})
        if isinstance(raw_operation, dict):
            metadata["operation"] = raw_operation.get("choice")
        if isinstance(metadata.get("operation"), str):
            raw_target = answers.get(metadata["operation"].lower() + "_target", {})
            if isinstance(raw_target, dict):
                metadata["target"] = raw_target.get("choice")
        operation_answer = validate_choice(result["answers"].get("operation", {}), operations)
        operation = operation_answer["choice"]
        target = None
        target_answer = None
        probabilities = {}
        if operation in targets:
            # Unused target heads cannot cause an action. Validate the head selected by the operation.
            target_answer = validate_choice(
                result["answers"].get(operation.lower() + "_target", {}), targets[operation],
            )
            target = target_answer["choice"]
            choice = targets[operation][target]["id"]
            probabilities = {a["id"]: target_answer["probabilities"][index] for index, a in targets[operation].items()}
        else:
            choice = controls[operation]["id"] if operation in controls else operation
            probabilities[choice] = operation_answer["probabilities"][operation]
        # Only a CLICK or SELECT can commit; an unused answer is never validated or consumed.
        commit_probability = 0
        if operation in {"CLICK", "SELECT"}:
            commit_probability = validate_noul(result["answers"].get(commit_question(target), {}))
    except (KeyError, TypeError, ValueError, AttributeError) as error:
        raise InvalidDecision(metadata) from error
    return {
        "choice": choice,
        "operation": operation,
        "target": target,
        "commit_probability": commit_probability,
        "confidence": operation_answer["confidence"],
        "probabilities": probabilities,
        "operation_probabilities": operation_answer["probabilities"],
        "target_probabilities": target_answer["probabilities"] if target_answer else {},
        "target_confidence": target_answer["confidence"] if target_answer else None,
        "raw_answers": result["answers"],
        **response_metadata,
        "request": body,
    }


def field_context(goal, action, page, history):
    return {
        "goal": goal,
        "field": {k: action.get(k) for k in ("label", "role", "value")},
        "page": {"title": page["title"], "text": page["text"][:6000]},
        "recent_actions": [{k: h.get(k) for k in ("action", "text")} for h in history[-6:]],
    }


def field_text(context, *, check_stop=None, remaining_budget=None, on_response=None):
    key = os.environ.get("TEXT_MODEL_API_KEY")
    if not key:
        raise ValueError("TYPE_TEXT needs TEXT_MODEL_API_KEY; no text is hardcoded or guessed by the executor.")
    base = os.environ.get("TEXT_MODEL_BASE_URL", "https://api.deepseek.com/v1").rstrip("/")
    model = os.environ.get("TEXT_MODEL", "deepseek-chat")
    reasoning = {"thinking": {"type": "disabled"}} if "api.deepseek.com/" in base else {"reasoning": {"effort": "low"}}
    if os.environ.get("TEXT_MODEL_REASONING") == "none":
        reasoning = {"reasoning": {"enabled": False}}
    started = time.perf_counter()
    control = {"check_stop": check_stop, "remaining_budget": remaining_budget} if check_stop else {}
    result = post_json(
        base + "/chat/completions",
        key,
        {
            "model": model,
            "max_tokens": 1024,
            "response_format": {"type": "json_object"},
            **reasoning,
            "messages": [
                {"role": "system", "content": TEXT_VALUE},
                {
                    "role": "user",
                    "content": json.dumps(context),
                },
            ],
        },
        **control,
    )
    metadata = {
        "model": model,
        "latency_ms": round((time.perf_counter() - started) * 1000),
        "usage": result["usage"] if isinstance(result, dict) and isinstance(result.get("usage"), dict) else {},
    }
    if on_response:
        on_response(metadata)
    if check_stop:
        check_stop()
    try:
        output = json.loads(result["choices"][0]["message"]["content"])
        value = output["text"]
        # An exact {"text": null} means the goal lacks this value, which Claude can supply; anything else is invalid.
        if output != {"text": None} and (
            set(output) != {"text"} or not isinstance(value, str) or not value.strip() or len(value) > 2000
        ):
            raise ValueError()
    except (ValueError, KeyError, TypeError):
        raise ValueError("Text helper returned no valid field value; nothing typed.") from None
    if value is None:
        raise ValueError(f"The goal gives no value for '{context['field']['label']}'; nothing typed.")
    return value, metadata
