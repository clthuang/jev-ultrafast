"""Run a goal with an explicit --allowed-operations list (an empty list is read only)."""

import argparse

from jev_ultrafast import Agent
from jev_ultrafast.contracts import SUPPORTED_OPERATIONS

parser = argparse.ArgumentParser()
parser.add_argument("--url", required=True)
parser.add_argument("--goal", action="append", required=True, help="Repeat for an ordered list of goals.")
parser.add_argument("--allowed-operations", nargs="*", choices=sorted(SUPPORTED_OPERATIONS), required=True)
args = parser.parse_args()

with Agent(args.url, args.goal, allowed_operations=args.allowed_operations) as agent:
    for state in agent.run():
        print(f"{state['elapsed_ms']:>5} ms  {len(state['history'])} actions  {state['status']}")
    print(state["page"]["url"])
