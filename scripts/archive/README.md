# Legacy OSINT Assets Archive

This directory contains legacy migration scripts, one-off backfill utilities, and debugging tools used during the development phase.

> [!CAUTION]
> These scripts are for **reference only**. Do NOT execute them in the production environment as they may interact with older schema versions or reset system state.

### Contents
- `migrate_*.py`: Database schema and auth migration history.
- `backfill_*.py`: Initial data population logic.
- `test_*.py`: Component-level verification scripts.
- `verify_*.py`: Historic integration checks.
