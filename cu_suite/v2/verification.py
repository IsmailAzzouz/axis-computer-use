"""Aggregate verified effects without inventing individual click observations."""


def effects_verified(steps):
    verified = {i for i, step in enumerate(steps)
                if step.get("verification") == "met" and not step.get("error") and step.get("dispatch") != "unknown"}
    for ordinal, parent in enumerate(steps):
        scope = parent.get("verification_scope")
        if ordinal not in verified or not isinstance(scope, dict):
            continue
        first, count = scope.get("first_step"), scope.get("step_count")
        output = parent.get("output")
        if (type(first) is not int or type(count) is not int or first < 0 or count <= 0 or
                first+count != ordinal or not isinstance(output, dict) or
                not isinstance(parent.get("id"), str)):
            continue
        members = steps[first:ordinal]
        if (scope.get("kind") == "triggered_demonstration" and parent.get("op") == "watch" and
                parent.get("dispatch") == "not_sent" and count == 1 and
                isinstance(output.get("sequence"), list) and output["sequence"]):
            trigger = members[0]
            if (trigger.get("op") in ("click", "keys") and trigger.get("id") == scope.get("trigger_id") and
                    trigger.get("dispatch") == "sent" and trigger.get("verification") == "unobservable" and
                    not trigger.get("error")):
                verified.add(first)
            continue
        if (scope.get("kind") != "sequence_acceptance" or parent.get("op") != "replay" or
                parent.get("dispatch") != "sent" or output.get("replayed") != count):
            continue
        # Only the exact internal replay clicks can be covered by its acceptance
        # predicate, never arbitrary earlier dispatch-only inputs or other steps.
        if all(step.get("op") == "click" and step.get("id") == f"{parent['id']}-{index}" and
               step.get("dispatch") == "sent" and step.get("verification") == "unobservable" and
               not step.get("error") for index, step in enumerate(members)):
            verified.update(range(first, ordinal))
    return bool(steps) and len(verified) == len(steps)
