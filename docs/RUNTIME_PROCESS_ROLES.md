# Runtime process roles

The paper lab intentionally runs three Kalshi-related supervised services:

| Service | Role | Execution authority |
| --- | --- | --- |
| `trading-platform-kalshi-predictions.service` | Predictions demo candidate/evaluation worker | Demo-only; global live guard remains false |
| `trading-platform-kalshi-perps.service` | Perps demo candidate/evaluation worker | Demo-only; global live guard remains false |
| `trading-platform-kalshi-reconciliation.service` | Read-only legacy/provider reconciliation | `broker_control=false`, `execution_enabled=false` |

The reconciliation worker may invoke the shared cycle module, but its persisted
role is `engine=reconciliation` and its safety gate must fail closed. Therefore
process-singularity audits must count execution workers by role, not by script
filename. A third process is expected only when it belongs to the supervised
reconciliation service; an unsupervised loop or a second worker for the same
execution role is a defect.
