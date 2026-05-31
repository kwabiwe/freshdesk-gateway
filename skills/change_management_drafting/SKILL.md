# Change Management Drafting Skill

Version: 2.0.0

Convert sparse technical notes, pasted emails, chat messages, implementation plans, vendor updates, customer requests and engineer notes into a complete operational change record suitable for a Freshdesk-style change ticket.

This skill is intended for infrastructure, network, security, cloud, application connectivity and vendor-supported operational changes. It should be especially effective when the input is incomplete, informal or written as rough engineering notes.

## Primary Objective

Produce a clear, technically accurate and approval-ready change document from the information provided.

The output must help an engineer, approver or customer understand:

- Why the change is needed.
- What is changing.
- Which systems, services or configuration items are affected.
- How the change will be implemented.
- How the change will be verified.
- How the change will be rolled back or safely abandoned.
- What assumptions or unknowns need to be confirmed before approval.

Do not simply reformat the supplied notes. Interpret them intelligently and turn them into a usable operational change record.

## Input Types

The input may include any combination of:

- Rough engineer notes.
- Pasted emails.
- Customer requests.
- Vendor instructions.
- Previous implementation plans.
- Chat messages.
- Ticket comments.
- Device lists.
- Hostnames.
- Change windows.
- Software versions.
- Firmware versions.
- Certificate details.
- Firewall, routing, load balancer or DNS notes.
- Validation steps.
- Rollback comments.
- Risk comments.

Treat all supplied text as evidence, but remove conversational filler.

## Evidence Handling Rules

- Treat every supplied note, email, plan and customer statement as evidence.
- Extract facts, commitments, sequencing, configuration items, dependencies, risks, dates, environments, affected services and validation requirements.
- Preserve technical names exactly, including hostnames, device names, certificate names, software versions, firmware versions, sites, regions, environments, application names and load balancer names.
- Preserve the intended order of operations where the input provides one.
- Remove greetings, sign-offs, duplicated wording and conversational filler.
- Do not claim that a test, approval, download, upload, staging test or customer confirmation has completed unless the evidence explicitly says it has completed.
- Use `TBD` for unsupported values rather than inventing details.
- Do not invent IP addresses, ports, vendors, approvers, engineers, timings, access methods, maintenance windows, software versions, business impact, monitoring tools or customer contacts.
- If a value is likely but not evidenced, include it as an assumption rather than as a fact.
- If multiple interpretations are possible, choose the safest operational interpretation and record it in the assumptions.
- Do not mention AI, prompts, models, automation or these instructions in the output.

## Date and Time Rules

- Resolve relative dates using the supplied local date and timezone when available.
- If the user says “next Tuesday”, “tomorrow”, “yesterday”, “tonight” or similar, convert it to a specific date where possible.
- Record date interpretation in the assumptions array.
- If the date cannot be confidently resolved, use `TBD` and add an assumption requiring confirmation.
- Do not invent a start time, end time or change duration unless supplied.
- If the user provides a date but no time, use the date and set time-related fields to `TBD`.

## Tone and Writing Style

Use clear British English.

The writing should sound like a competent network engineer or change manager wrote it. It should be professional, concise and practical.

Avoid:

- Overly generic corporate filler.
- Vague statements such as “perform necessary checks” without specifying the checks.
- Marketing language.
- Excessively formal wording.
- Unsupported certainty.
- Long, dense paragraphs.
- Repeating the same point in multiple sections.

Prefer:

- Clear operational language.
- Specific technical references.
- Numbered implementation steps.
- Short paragraphs.
- Conservative assumptions.
- Explicit verification and rollback checks.
- Customer-friendly phrasing where the change will be visible to a customer.

## Change Classification Rules

Unless the gateway or schema provides specific values:

- Prefer `Normal` as the change type.
- Use `Standard` only if the input explicitly states that this is a pre-approved standard change or matches a known standard change template.
- Use `Emergency` only if the input clearly states that the change is urgent, service-impacting, required immediately to restore service, or explicitly described as an emergency.
- Prefer `Pending approval` as the workflow state unless the input clearly states a different state.
- Prefer `Medium` risk if production systems are affected and no better risk rating is supplied.
- Prefer `Low` risk for non-production, documentation-only, monitoring-only or no-impact changes.
- Prefer `High` risk where the change affects critical production services, authentication, encryption, routing, firewalls, load balancers, HSMs, identity systems, financial services, internet edge, or where rollback is uncertain.
- Record any inferred classification in assumptions.

## Required Change Sections

Generate the following sections where supported by the gateway schema.

### Title

Create a concise title that includes:

- Customer or environment where known.
- Main system or service.
- Main activity.
- Version or feature where relevant.

Examples:

- `Wise UK HSM Firmware Upgrade to Version 2.3a and mTLS Rollout`
- `Production Firewall Policy Update for New Partner Connectivity`
- `LD5 Load Balancer Pool Update for Stargate HSM Validation`

### Background

Explain why the change is needed.

Infer the background from the notes where appropriate, but keep it conservative.

The background should include:

- Current state.
- Reason for the change.
- Any known issue, bug, dependency, lifecycle driver, security requirement or customer requirement.
- Any useful context from emails or previous plans.
- Why the proposed sequence makes sense.

Do not overstate benefits. If the notes only imply a benefit, phrase it as an intended outcome.

### Description

Explain what will change.

The description should include:

- Systems or services affected.
- High-level implementation approach.
- Whether the work is phased.
- Whether validation will occur before production reintroduction.
- Whether temporary routing, load balancer, certificate, firmware, DNS, firewall, application or routing changes are involved.
- Expected final state.

### Configuration Items

Identify all configuration items from the evidence.

Configuration items may include:

- Network devices.
- Firewalls.
- Routers.
- Switches.
- Load balancers.
- HSMs.
- Servers.
- Applications.
- Certificates.
- Firmware images.
- Software packages.
- Cloud resources.
- DNS records.
- NAT rules.
- Firewall policies.
- VPNs.
- Monitoring tools.
- Engineer laptops or tooling where they are material to the change.

For each configuration item, include:

- Name.
- Type.
- Environment or site where known.
- Role in the change.
- Version where known.

Use `TBD` for unknown fields.

### Dependencies

Include dependencies where supported by the schema.

Common dependencies include:

- Customer approval.
- Vendor attendance or guidance.
- Maintenance window.
- Engineer access.
- Firmware or software image availability.
- Hash or checksum validation.
- Certificate availability.
- Staging validation.
- Load balancer readiness.
- Application release readiness.
- Monitoring availability.
- Backup or export completion.
- Peer review.
- Change freeze exceptions.

### Implementation Steps

Expand the implementation into ordered, actionable steps.

The steps must be realistic enough for an engineer to follow.

Rules:

- Use numbered, sequential steps.
- Start with pre-change readiness checks where appropriate.
- Include isolation or draining steps before modifying production components.
- Include backup, export or current-state capture where relevant.
- Include the actual configuration or upgrade work.
- Include staged validation before wider rollout.
- Include reintroduction into production.
- Include communication or customer confirmation where evidenced or appropriate.
- Preserve the sequence from the supplied notes unless it is unsafe or unclear.
- If the notes are sparse, infer sensible operational steps and mark them as assumptions if meaningful.

For network and infrastructure changes, consider whether these apply:

- Capture current configuration.
- Capture current state, status, routes, pools, members, sessions or health checks.
- Confirm access to management interfaces.
- Confirm out-of-band or alternative access where relevant.
- Drain traffic before changes.
- Remove device from load balancer pool before upgrade.
- Apply change to one device first.
- Validate health.
- Repeat for remaining devices.
- Reintroduce into service.
- Monitor logs, alarms and customer-facing behaviour.

### Rollback Plan

Create a practical rollback plan.

Rollback must be specific to the change, not generic.

Include different rollback branches if failure points differ materially.

Common rollback branches:

- Failure before production traffic is affected.
- Failure during upgrade or configuration.
- Failure during validation.
- Failure after production reintroduction.
- Failure caused by application release.
- Failure caused by certificate, mTLS, firewall, routing or load balancer behaviour.

Rollback should explain:

- What gets removed, reverted or disabled.
- How traffic is returned to the known-good path.
- Whether old devices remain in service.
- Whether firmware rollback is possible or subject to vendor support.
- What checks confirm rollback success.

Do not state that firmware downgrade or restore is possible unless the evidence says it is possible. If unclear, say that rollback is subject to vendor-supported options.

### Verification Plan

Separate verification into:

- Pre-change verification.
- In-change verification.
- Post-change verification.

Verification must be specific and testable.

Examples of good verification:

- Confirm device is reachable.
- Confirm current firmware version.
- Confirm new firmware version after upgrade.
- Confirm expected load balancer pool membership.
- Confirm health checks are passing.
- Confirm certificates are installed and valid.
- Confirm mTLS handshake succeeds.
- Confirm application can send commands successfully.
- Confirm production-scenario transaction or command completes.
- Confirm no unexpected alarms are present.
- Confirm customer validates expected service behaviour.

Avoid vague checks such as:

- Confirm everything is working.
- Monitor system.
- Validate change.

If monitoring is included, specify what should be checked where possible.

### Risk and Impact

Include risk and impact where supported by the schema.

State:

- Whether production is affected.
- Whether resilience is reduced during the change.
- Whether there is a risk of service interruption.
- Whether customer traffic may be affected.
- Whether there are security, encryption, authentication or certificate risks.
- Whether the work is phased to reduce risk.
- Whether rollback is straightforward or dependent on vendor support.

Do not exaggerate impact. If impact is unclear, state that it is `TBD` and add an assumption.

### Communication Plan

Where appropriate, include:

- Customer to confirm readiness before work starts.
- Engineer to provide start notification.
- Engineer to provide progress updates at key stages.
- Customer to confirm application-level validation.
- Engineer to provide completion notification.
- Engineer to provide rollback notification if required.

Use only if the schema supports it or if a general notes field is available.

### Success Criteria

State the conditions that make the change successful.

Success criteria should be measurable.

Examples:

- All target devices are running the expected firmware version.
- Required certificates are installed.
- mTLS connectivity succeeds.
- Application commands complete successfully.
- Load balancer pools contain the expected members.
- Monitoring shows no unexpected alarms.
- Customer confirms expected service behaviour.

## Configuration Item Detection Guidance

Pay close attention to names and terms that indicate configuration items.

Examples:

- `wiseld5-hsm-1` is likely an HSM in LD5.
- `LD5` and `LD8` are likely sites or data centre locations.
- `Stargate` is likely an application or service.
- `HSM software image version 2.3a` is a firmware or software package.
- `MD5 hashes` are validation artefacts.
- `server certs`, `TLS certificates` and `mTLS certificates` are certificate configuration items.
- `separate HSM load balancer` is a temporary or validation load balancer path.
- `main load balancer` is the production load balancer path.
- `9K in Staging` is likely a staging test platform or device.

Do not normalise or rename technical items unless the input clearly contains a typo. Preserve the original names.

## Assumption Rules

Use assumptions to make the ticket useful without pretending unsupported facts are confirmed.

Add assumptions for:

- Inferred background.
- Inferred change type.
- Inferred risk.
- Resolved relative dates.
- Whether an environment is production.
- Whether a device belongs to a site based on naming.
- Whether a load balancer is temporary or production.
- Whether vendor guidance is required.
- Whether rollback depends on vendor-supported downgrade options.
- Whether customer validation is required.

Good assumptions:

- `Assumed this is a Normal change because it is planned work and no emergency wording was provided.`
- `Assumed the Wise UK HSM estate is production because the notes refer to production-scenario command testing and the main load balancer.`
- `Assumed LD5 and LD8 refer to separate data centre or site locations based on the HSM naming convention.`
- `Assumed firmware rollback is subject to vendor-supported downgrade or recovery options because the notes do not confirm a tested downgrade path.`

Bad assumptions:

- `The change will take two hours.`
- `The customer has approved the change.`
- `The firewall rules are already configured.`
- `The certificates are valid until 2027.`

## Unknowns and TBD Rules

Use `TBD` for any important unknown.

Common `TBD` fields:

- Change window start time.
- Change window end time.
- Implementation engineer.
- Approver.
- Customer technical contact.
- Exact maintenance window.
- Service impact.
- Monitoring platform.
- Backout duration.
- Vendor contact.
- CAB reference.
- Freshdesk ticket reference.
- IP addresses.
- Ports.
- Exact commands.

Do not leave important unknowns hidden. Either place them in the correct field as `TBD` or list them in assumptions or open questions, depending on the schema.

## Output Contract

Return one JSON object only.

The JSON must match the schema supplied by the gateway exactly.

If the gateway supplies a schema:

- Use only fields from that schema.
- Use arrays for implementation steps, rollback steps, verification checks, assumptions, risks, configuration items and dependencies where the schema allows.
- Do not add extra fields that are not present in the schema.
- If the schema has required fields and the input does not provide the information, use `TBD`.
- If the schema uses specific enum values, use only those values.
- If the schema uses field names such as `description`, `implementation_plan`, `rollback_plan`, `risk`, `impact`, `assets` or `configuration_items`, map the generated content into those fields.

If no schema is supplied, use this default JSON structure:

```json
{
  "title": "",
  "change_type": "Normal",
  "workflow_state": "Pending approval",
  "risk": "TBD",
  "impact": "TBD",
  "planned_start": "TBD",
  "planned_end": "TBD",
  "customer": "TBD",
  "environment": "TBD",
  "background": "",
  "description": "",
  "configuration_items": [
    {
      "name": "",
      "type": "",
      "site_or_environment": "TBD",
      "role_in_change": "",
      "version": "TBD"
    }
  ],
  "dependencies": [],
  "implementation_steps": [],
  "rollback_plan": {
    "summary": "",
    "steps": []
  },
  "verification": {
    "pre_change": [],
    "in_change": [],
    "post_change": []
  },
  "risks_and_mitigations": [
    {
      "risk": "",
      "mitigation": ""
    }
  ],
  "communication_plan": [],
  "success_criteria": [],
  "assumptions": [],
  "open_questions": []
}
```

Return valid JSON only. Do not wrap it in Markdown. Do not include explanatory text outside the JSON.

## Freshdesk Gateway Behaviour

When used by a gateway that creates Freshdesk tickets:

- Optimise for clear field population rather than long prose.
- Keep each field self-contained.
- Avoid references like “as above” because fields may be displayed independently.
- Keep implementation and verification steps as arrays so they can be rendered as checklist items.
- Keep assumptions separate so the user can correct them before submitting for approval.
- Ensure the title is suitable as a ticket subject.
- Ensure the description and background are understandable by a non-authoring approver.
- Ensure rollback is visible and credible.
- Include `TBD` items so the gateway can prompt for missing mandatory values later.

## Example 1: HSM Firmware Upgrade and mTLS Rollout

### Input

Next Tuesday, on the 2nd of June, I am carrying out a change for Wise UK to update their HSMs and roll out mTLS to four HSMs.

HSMs:

wiseld5-hsm-1
wiseld5-hsm-2
wiseld8-hsm-1
wiseld8-hsm-2

I shared a download link for the HSM software image needed to upgrade the HSM to version 2.3a first to resolve the bug to do with mTLS. The folder includes MD5 hashes for verifying the files.

I suggest upgrading the LD5 HSMs first as they already have TLS certificates loaded. After that, we need to update the server certs with the correct ones.

Previous plan:

Make sure laptop and firmware are ready.
Make sure new Stargate version is ready to test upgraded HSM and tested on 9K in Staging.
Upgrade one HSM with A24 guidance.
Add upgraded HSM to separate HSM load balancer.
Release new Stargate version that can send commands to separate HSM.
Test all commands.
If successful, upgrade another HSM.
Add upgraded HSMs to main load balancer.
Check commands have been run in production scenario on HSMs with new firmware.
If not, remove old firmware HSMs from main load balancer so only new firmware HSMs are used.
Upgrade rest of HSMs and add them to pool.

### Output

```json
{
  "title": "Wise UK HSM Firmware Upgrade to Version 2.3a and mTLS Rollout",
  "change_type": "Normal",
  "workflow_state": "Pending approval",
  "risk": "High",
  "impact": "TBD",
  "planned_start": "2026-06-02TBD",
  "planned_end": "TBD",
  "customer": "Wise UK",
  "environment": "Production",
  "background": "Wise UK requires a firmware upgrade across its HSM estate to version 2.3a before completing the mTLS rollout. The upgrade is required to resolve a known bug affecting mTLS functionality. The firmware image has been shared with Wise UK along with MD5 hashes so the files can be verified before use. The LD5 HSMs are planned to be upgraded first because TLS certificates are already loaded on those devices, after which the server certificates can be updated with the correct certificates.",
  "description": "This change will upgrade four Wise UK HSMs to firmware version 2.3a and support the rollout of mTLS across the HSM estate. The change will be carried out in a phased manner, starting with one LD5 HSM. The upgraded HSM will be validated through a separate HSM load balancer using a Stargate version capable of sending commands to that path. Once command validation is successful, additional HSMs will be upgraded, added back into the main load balancer pool and validated using production-scenario commands.",
  "configuration_items": [
    {
      "name": "wiseld5-hsm-1",
      "type": "HSM",
      "site_or_environment": "LD5 / Production",
      "role_in_change": "Target HSM for firmware upgrade and mTLS rollout",
      "version": "Target firmware 2.3a"
    },
    {
      "name": "wiseld5-hsm-2",
      "type": "HSM",
      "site_or_environment": "LD5 / Production",
      "role_in_change": "Target HSM for firmware upgrade and mTLS rollout",
      "version": "Target firmware 2.3a"
    },
    {
      "name": "wiseld8-hsm-1",
      "type": "HSM",
      "site_or_environment": "LD8 / Production",
      "role_in_change": "Target HSM for firmware upgrade and mTLS rollout",
      "version": "Target firmware 2.3a"
    },
    {
      "name": "wiseld8-hsm-2",
      "type": "HSM",
      "site_or_environment": "LD8 / Production",
      "role_in_change": "Target HSM for firmware upgrade and mTLS rollout",
      "version": "Target firmware 2.3a"
    },
    {
      "name": "HSM firmware image version 2.3a",
      "type": "Firmware image",
      "site_or_environment": "TBD",
      "role_in_change": "Software image used to upgrade the target HSMs",
      "version": "2.3a"
    },
    {
      "name": "MD5 hash files",
      "type": "Validation artefact",
      "site_or_environment": "TBD",
      "role_in_change": "Used to verify the integrity of the downloaded firmware image",
      "version": "TBD"
    },
    {
      "name": "Stargate",
      "type": "Application",
      "site_or_environment": "Production / Staging",
      "role_in_change": "Used to send commands to upgraded HSMs for validation",
      "version": "New version, exact version TBD"
    },
    {
      "name": "Separate HSM load balancer",
      "type": "Load balancer",
      "site_or_environment": "TBD",
      "role_in_change": "Temporary validation path for upgraded HSMs before return to main production pool",
      "version": "TBD"
    },
    {
      "name": "Main HSM load balancer",
      "type": "Load balancer",
      "site_or_environment": "Production",
      "role_in_change": "Main production HSM traffic path",
      "version": "TBD"
    }
  ],
  "dependencies": [
    "Firmware image version 2.3a must be available before the change starts.",
    "MD5 hash validation must be completed before the firmware image is used.",
    "Required TLS and mTLS certificates must be available.",
    "New Stargate version must be available for validation.",
    "Stargate testing against the 9K staging device must be confirmed.",
    "A24 guidance must be available during the HSM upgrade activity.",
    "Separate HSM load balancer must be available for validation.",
    "Main HSM load balancer access must be available to remove and add HSMs as required."
  ],
  "implementation_steps": [
    "Confirm engineer laptop, access and required tooling are available.",
    "Confirm the HSM firmware image version 2.3a is available.",
    "Verify the firmware image using the supplied MD5 hashes.",
    "Confirm required TLS and mTLS certificates are available.",
    "Confirm the new Stargate version is available and has been tested against the 9K staging device.",
    "Confirm the current state of the main HSM load balancer pool.",
    "Start with the LD5 HSMs because TLS certificates are already loaded on those devices.",
    "Isolate the first LD5 HSM from normal production traffic as agreed with Wise UK.",
    "Upgrade the first LD5 HSM to firmware version 2.3a with A24 guidance.",
    "Update the server certificate on the upgraded HSM with the correct certificate where required.",
    "Add the upgraded HSM to the separate HSM load balancer.",
    "Enable or release the Stargate version that can send commands to the separate HSM load balancer.",
    "Test all required commands against the upgraded HSM.",
    "If command testing is successful, upgrade the second LD5 HSM using the same process.",
    "Add the upgraded LD5 HSMs to the main HSM load balancer pool.",
    "Confirm production-scenario commands are being processed successfully by HSMs running firmware version 2.3a.",
    "If production-scenario commands have not run on upgraded HSMs, remove old firmware HSMs from the main load balancer so traffic is directed only to upgraded HSMs.",
    "Upgrade wiseld8-hsm-1 with A24 guidance and validate it.",
    "Upgrade wiseld8-hsm-2 with A24 guidance and validate it.",
    "Add all upgraded HSMs back into the main production HSM load balancer pool.",
    "Confirm all four HSMs are running firmware version 2.3a.",
    "Confirm mTLS is operating as expected across the upgraded HSM estate."
  ],
  "rollback_plan": {
    "summary": "Rollback will depend on the point of failure. The safest rollback approach is to keep failed or unvalidated HSMs out of the production load balancer pool and continue service using known-good HSMs. Firmware downgrade or recovery is subject to vendor-supported options.",
    "steps": [
      "If an issue occurs before an upgraded HSM is returned to production, keep the affected HSM isolated from production traffic.",
      "Remove the affected HSM from the separate HSM load balancer if it has been added.",
      "Continue running production traffic through the remaining known-good HSMs.",
      "Investigate the issue with A24 guidance.",
      "Revert certificate or mTLS configuration changes on the affected HSM if they are identified as the cause.",
      "If firmware rollback is required, follow the vendor-supported downgrade or recovery process.",
      "If an issue occurs after an upgraded HSM is added to the main load balancer, remove the affected HSM from the main production pool.",
      "Confirm traffic is being served by the remaining healthy HSMs.",
      "Revert Stargate routing or configuration to the previous production HSM path if required.",
      "Re-add only known-good HSMs to the main production load balancer pool.",
      "Confirm production command execution succeeds through the restored known-good HSM pool."
    ]
  },
  "verification": {
    "pre_change": [
      "Confirm all four HSMs are reachable.",
      "Confirm current firmware versions.",
      "Confirm current main load balancer pool membership.",
      "Confirm firmware image version 2.3a is available.",
      "Confirm firmware image passes MD5 hash validation.",
      "Confirm required TLS and mTLS certificates are available.",
      "Confirm LD5 HSMs already have TLS certificates loaded.",
      "Confirm new Stargate version has been tested against the 9K staging device.",
      "Confirm A24 guidance is available."
    ],
    "in_change": [
      "Confirm each HSM upgrade completes successfully.",
      "Confirm each upgraded HSM reports firmware version 2.3a.",
      "Confirm correct server certificates are applied where required.",
      "Confirm upgraded HSMs can be added to the separate HSM load balancer.",
      "Confirm Stargate can send commands to upgraded HSMs through the separate load balancer.",
      "Confirm all required commands complete successfully.",
      "Confirm upgraded HSMs can be added back into the main production load balancer pool.",
      "Confirm production-scenario commands are processed successfully by upgraded HSMs."
    ],
    "post_change": [
      "Confirm all four HSMs are running firmware version 2.3a.",
      "Confirm all four HSMs are present in the expected production load balancer pool.",
      "Confirm mTLS connectivity is working as expected.",
      "Confirm command execution is successful across the upgraded HSMs.",
      "Confirm no unexpected Stargate errors are observed.",
      "Confirm no unexpected HSM-related alerts are present.",
      "Confirm Wise UK is satisfied that the service is operating as expected."
    ]
  },
  "risks_and_mitigations": [
    {
      "risk": "Production HSM resilience may be reduced while individual HSMs are isolated, upgraded or validated.",
      "mitigation": "Upgrade the HSMs in a phased manner and keep known-good HSMs in service wherever possible."
    },
    {
      "risk": "mTLS or certificate configuration may prevent successful application communication.",
      "mitigation": "Validate certificates and command execution using the separate HSM load balancer before returning upgraded HSMs to the main production pool."
    },
    {
      "risk": "Firmware upgrade may fail or introduce unexpected behaviour.",
      "mitigation": "Upgrade one HSM first with A24 guidance and validate before proceeding with the remaining HSMs."
    }
  ],
  "communication_plan": [
    "Confirm readiness with Wise UK before starting the change.",
    "Notify Wise UK when the first HSM upgrade starts.",
    "Provide progress updates after each HSM is upgraded and validated.",
    "Notify Wise UK before adding upgraded HSMs back into the main production load balancer.",
    "Confirm completion and request Wise UK service validation."
  ],
  "success_criteria": [
    "All four HSMs are upgraded to firmware version 2.3a.",
    "Firmware image integrity has been verified using the supplied MD5 hashes before use.",
    "Correct TLS and mTLS certificates are applied.",
    "Stargate can successfully send commands to the upgraded HSMs.",
    "Production-scenario commands complete successfully on HSMs running firmware version 2.3a.",
    "All upgraded HSMs are added back into the main production load balancer pool.",
    "Wise UK confirms the service is operating as expected."
  ],
  "assumptions": [
    "Assumed this is a Normal change because it is planned work and no emergency wording was provided.",
    "Assumed the workflow state is Pending approval because no current approval state was supplied.",
    "Assumed the Wise UK HSM estate is production because the notes refer to production-scenario command testing and the main load balancer.",
    "Assumed the change risk is High because the change affects production HSMs, firmware, certificates and mTLS.",
    "Assumed LD5 and LD8 refer to separate sites or data centre locations based on the HSM naming convention.",
    "Assumed firmware rollback is subject to vendor-supported downgrade or recovery options because the notes do not confirm a tested downgrade path.",
    "Assumed 2 June is the planned change date based on the supplied note."
  ],
  "open_questions": [
    "Confirm the planned change start and end time.",
    "Confirm the expected customer impact during individual HSM upgrades.",
    "Confirm the exact Stargate version to be used.",
    "Confirm whether firmware downgrade has been tested or is vendor-supported.",
    "Confirm the monitoring platform or checks to be used during and after the change.",
    "Confirm who from Wise UK will provide application-level validation.",
    "Confirm whether A24 attendance is formally scheduled for the change window."
  ]
}
```

## Example 2: Sparse Firewall Rule Request

### Input

Need a change for Acme. Allow new SFTP traffic from 10.10.50.25 to partner 203.0.113.15 on TCP 22. Production firewall. Doing it Thursday night. Rollback is remove rule. Verify with test connection.

### Output

```json
{
  "title": "Acme Production Firewall Rule Update for Partner SFTP Connectivity",
  "change_type": "Normal",
  "workflow_state": "Pending approval",
  "risk": "Medium",
  "impact": "TBD",
  "planned_start": "TBD",
  "planned_end": "TBD",
  "customer": "Acme",
  "environment": "Production",
  "background": "Acme requires a production firewall policy update to allow SFTP connectivity from an internal source host to a partner endpoint. The requested traffic is TCP 22 from 10.10.50.25 to 203.0.113.15.",
  "description": "This change will add a production firewall rule allowing SFTP traffic from 10.10.50.25 to partner IP address 203.0.113.15 on TCP port 22. The change will be verified using a test SFTP or TCP connection after implementation.",
  "configuration_items": [
    {
      "name": "Production firewall",
      "type": "Firewall",
      "site_or_environment": "Production",
      "role_in_change": "Target firewall for rule update",
      "version": "TBD"
    },
    {
      "name": "10.10.50.25",
      "type": "Source host",
      "site_or_environment": "TBD",
      "role_in_change": "Source of SFTP traffic",
      "version": "TBD"
    },
    {
      "name": "203.0.113.15",
      "type": "Partner endpoint",
      "site_or_environment": "External / Partner",
      "role_in_change": "Destination for SFTP traffic",
      "version": "TBD"
    }
  ],
  "dependencies": [
    "Firewall management access must be available.",
    "Source host must be available for testing.",
    "Partner endpoint must be reachable and listening on TCP 22.",
    "Approval must be obtained before implementation."
  ],
  "implementation_steps": [
    "Confirm the production firewall to be modified.",
    "Capture or export the current firewall policy configuration before making changes.",
    "Add a firewall rule allowing traffic from 10.10.50.25 to 203.0.113.15 on TCP port 22.",
    "Place the rule in the appropriate policy order to allow the intended traffic only.",
    "Commit or publish the firewall policy change.",
    "Confirm the policy installs successfully without errors.",
    "Run a test connection from 10.10.50.25 to 203.0.113.15 on TCP port 22.",
    "Confirm the firewall logs show the expected allowed traffic."
  ],
  "rollback_plan": {
    "summary": "Rollback is to remove the newly added firewall rule and restore the previous policy state.",
    "steps": [
      "Remove the newly added firewall rule allowing 10.10.50.25 to 203.0.113.15 on TCP 22.",
      "Commit or publish the firewall policy change.",
      "Confirm the policy installs successfully.",
      "Confirm traffic from 10.10.50.25 to 203.0.113.15 on TCP 22 is no longer allowed by the removed rule.",
      "Confirm no unrelated firewall rules were changed."
    ]
  },
  "verification": {
    "pre_change": [
      "Confirm the current firewall policy is accessible.",
      "Confirm the requested source IP is 10.10.50.25.",
      "Confirm the requested destination IP is 203.0.113.15.",
      "Confirm the requested destination port is TCP 22."
    ],
    "in_change": [
      "Confirm the firewall policy change commits or publishes successfully.",
      "Confirm the new rule appears in the intended policy position.",
      "Confirm there are no policy installation errors."
    ],
    "post_change": [
      "Confirm a test connection from 10.10.50.25 to 203.0.113.15 on TCP 22 succeeds.",
      "Confirm firewall logs show the expected allowed traffic.",
      "Confirm there are no unexpected firewall alerts related to the change."
    ]
  },
  "risks_and_mitigations": [
    {
      "risk": "Firewall rule may allow unintended access if configured too broadly.",
      "mitigation": "Restrict the rule to the supplied source IP, destination IP and TCP port 22 only."
    },
    {
      "risk": "Policy ordering may prevent the new rule from matching traffic.",
      "mitigation": "Place the rule in the appropriate policy order and verify using firewall logs."
    }
  ],
  "communication_plan": [
    "Notify Acme before starting the change.",
    "Notify Acme once the firewall rule has been implemented.",
    "Request confirmation that SFTP connectivity works as expected."
  ],
  "success_criteria": [
    "Firewall policy installs successfully.",
    "Traffic from 10.10.50.25 to 203.0.113.15 on TCP 22 is allowed.",
    "Firewall logs show the expected permitted traffic.",
    "Acme confirms SFTP connectivity works as expected."
  ],
  "assumptions": [
    "Assumed this is a Normal change because it is planned work and no emergency wording was provided.",
    "Assumed the workflow state is Pending approval because no current approval state was supplied.",
    "Assumed Thursday night refers to the next upcoming Thursday night, but the exact date and time must be confirmed.",
    "Assumed the change risk is Medium because it affects a production firewall but is limited to a specific source, destination and port."
  ],
  "open_questions": [
    "Confirm the exact change date and time.",
    "Confirm the production firewall name.",
    "Confirm whether NAT is required.",
    "Confirm whether the partner expects traffic from the original source IP or a translated IP.",
    "Confirm who will perform the SFTP test."
  ]
}
```

## Example 3: Load Balancer Pool Member Replacement

### Input

Create change. Customer Globex. Replace app01 with app03 in prod LB pool for payments API. app03 has already been built and tested by app team. Need to drain app01 first, add app03, check health, then remove app01. Rollback put app01 back and remove app03.

### Output

```json
{
  "title": "Globex Production Load Balancer Pool Update for Payments API",
  "change_type": "Normal",
  "workflow_state": "Pending approval",
  "risk": "Medium",
  "impact": "TBD",
  "planned_start": "TBD",
  "planned_end": "TBD",
  "customer": "Globex",
  "environment": "Production",
  "background": "Globex requires an update to the production load balancer pool supporting the Payments API. The change will replace app01 with app03. The application team has already built and tested app03.",
  "description": "This change will update the production Payments API load balancer pool by draining app01, adding app03, confirming app03 health checks are passing, and then removing app01 from the pool. The intended final state is for app03 to serve production Payments API traffic in place of app01.",
  "configuration_items": [
    {
      "name": "Payments API production load balancer pool",
      "type": "Load balancer pool",
      "site_or_environment": "Production",
      "role_in_change": "Target pool to be updated",
      "version": "TBD"
    },
    {
      "name": "app01",
      "type": "Application server",
      "site_or_environment": "Production",
      "role_in_change": "Existing pool member to be drained and removed",
      "version": "TBD"
    },
    {
      "name": "app03",
      "type": "Application server",
      "site_or_environment": "Production",
      "role_in_change": "New pool member to be added",
      "version": "TBD"
    }
  ],
  "dependencies": [
    "Load balancer management access must be available.",
    "app03 must remain available and ready for production traffic.",
    "Application team validation of app03 must be accepted as a pre-change dependency.",
    "Monitoring or health check visibility must be available."
  ],
  "implementation_steps": [
    "Confirm current Payments API production load balancer pool membership.",
    "Confirm app01 is currently active in the pool.",
    "Confirm app03 is reachable from the load balancer.",
    "Confirm app03 has been built and tested by the application team.",
    "Drain app01 from the Payments API production load balancer pool.",
    "Confirm existing sessions on app01 have drained to the expected level.",
    "Add app03 to the Payments API production load balancer pool.",
    "Confirm app03 health checks are passing.",
    "Confirm app03 is receiving traffic as expected.",
    "Remove app01 from the production load balancer pool.",
    "Confirm final pool membership reflects app03 in service and app01 removed."
  ],
  "rollback_plan": {
    "summary": "Rollback is to remove app03 from the production load balancer pool and return app01 to service.",
    "steps": [
      "Remove or disable app03 from the Payments API production load balancer pool.",
      "Re-add or re-enable app01 in the Payments API production load balancer pool.",
      "Confirm app01 health checks are passing.",
      "Confirm app01 is receiving traffic as expected.",
      "Confirm Payments API service behaviour has returned to the previous known-good state."
    ]
  },
  "verification": {
    "pre_change": [
      "Confirm current Payments API production pool membership.",
      "Confirm app01 is active and healthy before the change.",
      "Confirm app03 is reachable by the load balancer.",
      "Confirm app03 testing has been completed by the application team."
    ],
    "in_change": [
      "Confirm app01 drains successfully.",
      "Confirm app03 can be added to the pool.",
      "Confirm app03 health checks pass.",
      "Confirm app03 starts receiving traffic."
    ],
    "post_change": [
      "Confirm final pool membership is correct.",
      "Confirm Payments API health checks are passing.",
      "Confirm application monitoring shows no unexpected errors.",
      "Confirm customer or application team validation is successful."
    ]
  },
  "risks_and_mitigations": [
    {
      "risk": "app03 may fail health checks or behave unexpectedly under production traffic.",
      "mitigation": "Add app03 before removing app01 and verify health checks and traffic behaviour before completing the change."
    },
    {
      "risk": "Removing app01 may reduce service capacity if app03 is not functioning correctly.",
      "mitigation": "Drain app01 first and only remove it once app03 is confirmed healthy."
    }
  ],
  "communication_plan": [
    "Notify Globex before starting the load balancer change.",
    "Notify Globex after app03 has been added and health checks are passing.",
    "Notify Globex once app01 has been removed and final validation is complete."
  ],
  "success_criteria": [
    "app03 is active and healthy in the Payments API production load balancer pool.",
    "app01 has been drained and removed from the pool.",
    "Payments API health checks are passing.",
    "No unexpected application or load balancer errors are observed."
  ],
  "assumptions": [
    "Assumed this is a Normal change because it is planned work and no emergency wording was provided.",
    "Assumed the workflow state is Pending approval because no current approval state was supplied.",
    "Assumed the change risk is Medium because it affects a production load balancer pool but has a clear rollback.",
    "Assumed app03 application testing has completed because the input states it has already been built and tested by the application team."
  ],
  "open_questions": [
    "Confirm the exact load balancer name.",
    "Confirm the planned change window.",
    "Confirm whether app01 should remain disabled or be removed completely after the change.",
    "Confirm who will provide application-level validation."
  ]
}
```
