# ShopAssist demo specification

**Status:** Approved 2026-09-06
**Supersedes:** CampusGPT as the primary DriftZero hackathon scenario

## Purpose

ShopAssist is a deterministic e-commerce support assistant whose retrieval layer
can be switched between a current and a retired store-policy corpus. It gives
DriftZero a repeatable knowledge-freshness failure with answers that judges can
verify immediately.

## Golden path

1. ShopAssist begins healthy on Returns Policy v2.1.
2. Questions about electronics, clearance items, refunds, and warranties return
   correct answers with citations.
3. The demo injects Returns Policy v1.4 into the active retrieval path.
4. ShopAssist confidently returns outdated or unsupported policy claims while
   latency, reliability, and safety remain healthy.
5. Each response emits simulated trace metadata including policy document ID,
   citation count, unsupported-claim count, quality, and groundedness.
6. DriftZero identifies a knowledge-freshness failure and recommends a corpus
   refresh plus citation-required mode.
7. Recovery restores v2.1 and subsequent answers are grounded again.
8. Reset returns the assistant to the initial healthy state.

## Canonical policy facts

| Topic | Current policy | Retired policy behavior |
| --- | --- | --- |
| General returns | 30 days | 30 days |
| Electronics | 14 days | Incorrectly treated as 30 days |
| Clearance | Final sale except damaged/defective items | Incorrectly treated as refundable |
| Smartwatch warranty | 12 months; defects only | Incorrectly claims two years and accidental coverage |
| Refund timing | 5–7 business days | Incorrectly claims two business days |

## Integration boundary

ShopAssist owns the customer-facing conversation, deterministic knowledge-state
controls, and production-shaped telemetry payloads. The existing DriftZero backend
owns scoring, incident creation, diagnosis, recovery approval, verification, and
audit history. ShopAssist must not execute a consequential commerce action.
