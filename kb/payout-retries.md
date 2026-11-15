# Failed payouts and retries
tags: PAYOUT_FAILED_TRANSIENT payout failed BANK_TIMEOUT BANK_DOWNTIME retry
When a payout fails because the bank timed out or was briefly unavailable, it is safe to retry it. The first retry is automatic. A second retry needs an operations team member to confirm the bank issue is resolved. Each retry carries a unique key so money can never be sent twice.
