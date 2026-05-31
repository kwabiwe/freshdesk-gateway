# Full Change Document Template

The gateway renders the structured record into Freshdesk rich HTML using this section order:

1. Change title
2. Change classification
3. Planned window, or planned change date when start and end are not known
4. Customer / environment
5. Configuration items
6. Background
7. Change description
8. Implementation steps
9. Rollback plan
10. Verification plan
   - Pre-change verification
   - In-change verification
   - Post-change verification
11. Risk and impact
12. Expected outcome
13. Success criteria
14. Risks and mitigations when present
15. Communication plan when present
16. Dependencies when present

Always populate the operational core. Use `TBD` where the source does not support a specific answer. The gateway displays assumptions, open questions, TBD values, validation blockers and field-mapping notes separately for local review. It does not include those internal review notes in the Freshdesk description.
