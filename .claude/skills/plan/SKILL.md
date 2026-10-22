---
name: plan
description: "Plan a change to agent-scaffold before writing code: assumptions, questions, steps with checks, risks"
argument-hint: "[what to build or fix]"
disable-model-invocation: true
---

Plan this change before writing any code: $ARGUMENTS

1. Read `AGENTS.md` and the files the change touches.
2. Restate the goal in one sentence, with how you'll know it's done.
3. List your assumptions, and the questions you need answered. If something blocks the plan, ask now and stop.
4. Propose the simplest approach. If there's a real alternative, give it in one line with the trade-off.
5. Write the steps, each with a check:
   `1. <step> -> verify: <test or command>`
6. Name the files you expect to change, and the risks: data, security, performance, and how people using it are affected (`.claude/rules/humane-design.md`).

Don't edit files. End by asking the user to approve or change the plan.
