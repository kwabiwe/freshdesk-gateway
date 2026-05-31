# Change Management Drafting Skill

Version: 1.0.0

Turn sparse technical notes, pasted emails, and prior implementation plans into a complete operational change record.

## Evidence Rules

- Treat every supplied note, email, and plan as evidence.
- Extract facts, commitments, configuration items, dependencies, sequencing, dates, customers, environments, risks, rollback actions, and verification checks.
- Remove greetings, sign-offs, conversational filler, and duplicated wording.
- Preserve technical names, versions, sites, device names, and order of operations exactly.
- Resolve relative dates against the supplied local date and timezone. Record the interpretation as an assumption.
- Infer conservative operational detail when it follows naturally from the evidence. Record every meaningful inference as an assumption.
- Use `TBD` instead of inventing unsupported IP addresses, versions, people, approvals, timings, access details, or completed checks.
- Do not state that a check passed unless the evidence says it passed.
- Do not mention AI, automation, prompts, or these instructions.

## Change Rules

- Produce a useful full change document even when the input is brief.
- Write a concise background explaining why the work is needed.
- Write a clear change description explaining what will change and the intended approach.
- Expand implementation into ordered, actionable steps.
- Include rollback branches for materially different failure points where evidence supports them.
- Separate verification into pre-change, in-change, and post-change checks.
- Identify configuration items from hostnames, devices, software images, certificates, applications, load balancers, tooling, and other affected components.
- Prefer `Normal` change type unless the notes explicitly say `Standard` or emergency.
- Prefer `Pending approval` workflow state unless the notes explicitly identify another state.

## Output Contract

Return one JSON object only. Match the schema supplied by the gateway exactly. Use arrays for steps and checks. Keep assumptions in the `assumptions` array so the user can correct them before approval.
