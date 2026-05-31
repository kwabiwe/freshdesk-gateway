# Wise UK HSM Upgrade And mTLS Rollout

Gold-standard example for change generation quality.

Sparse source notes should become a full operational change covering:

- Planned date: Tuesday 2 June 2026
- Customer and environment: Wise UK production HSM environment
- Configuration items: `wiseld5-hsm-1`, `wiseld5-hsm-2`, `wiseld8-hsm-1`, `wiseld8-hsm-2`
- Supporting items: firmware image version `2.3a`, MD5 hashes, TLS / mTLS certificates, Stargate, separate validation load balancer, main production load balancer, engineer laptop
- Background: upgrade firmware to resolve an mTLS-related bug and roll out mTLS
- Implementation: validate prerequisites, upgrade LD5 first, isolate and upgrade one HSM, test through the separate load balancer using Stargate, add known-good HSMs to the production pool, then upgrade LD8
- Rollback: isolate failed HSMs, remove affected pool members, revert certificate or Stargate changes where needed, restore known-good routing, and roll back firmware only where vendor-supported
- Verification: pre-change, per-HSM in-change, and final post-change checks
- Outcome: all four HSMs on `2.3a`, mTLS validated, and production traffic operating through the expected pool

Do not invent unsupported customer contacts, IP addresses, exact maintenance times, approvals, or completed checks.
