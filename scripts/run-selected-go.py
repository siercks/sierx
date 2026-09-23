"""Run a named Go integration test and reject missing or skipped execution."""
import json
import os
import subprocess
import sys


def check(events, required):
    package, test = required.rsplit(":", 1)
    selected = [e for e in events if e.get("Package") == package
                and (e.get("Test") == test or e.get("Test", "").startswith(test + "/"))]
    if any(e.get("Action") in {"skip", "fail"} for e in selected):
        raise ValueError("required test or subtest failed/skipped: " + required)
    actions = {e.get("Action") for e in selected if e.get("Test") == test}
    if not {"run", "pass"}.issubset(actions):
        raise ValueError("required test did not run and pass: " + required)


def main():
    required = os.environ["SIERX_EXPECT_GO_TEST"]
    if ":" not in required:
        raise ValueError("SIERX_EXPECT_GO_TEST must be package:TestName")
    events = []
    malformed = False
    with subprocess.Popen(["go", "test", "-json", *sys.argv[1:]],
                          stdout=subprocess.PIPE, text=True) as process:
        for line in process.stdout:
            try:
                event = json.loads(line)
                if not isinstance(event, dict):
                    raise ValueError("not an event")
            except ValueError:
                malformed = True
                print(line, end="", flush=True)
                continue
            if event.get("Output"):
                print(event["Output"], end="", flush=True)
            # Keep only status records, not the possibly large test log.
            if event.get("Action") != "output":
                events.append(event)
        status = process.wait()
    if status:
        return status
    if malformed:
        raise ValueError("Go test emitted malformed result records")
    check(events, required)
    print("selected-test: required test and subtests passed")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (KeyError, ValueError, OSError) as error:
        sys.exit("selected-test: " + str(error))
