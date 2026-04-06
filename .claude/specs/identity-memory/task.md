# Identity and Person Memory Types — Task Checklist

## Data Model
- [x] **Velasari** adds `IDENTITY`, `PERSON` to `MemoryType` enum in `models.py`
- [x] **Velasari** adds `DESCRIBES` to `RelType` enum in `models.py`

## Decay
- [x] **Velasari** adds identity (365.0) and person (90.0) to `get_initial_stability` defaults in `decay.py`

## Classification
- [x] **Velasari** adds `_IDENTITY_PATTERNS` and `_PERSON_PATTERNS` to `classification.py`
- [x] **Velasari** adds identity/person to `classify()` scores dict and scoring logic in `classification.py`
- [x] **Velasari** adds identity_bonus and person_bonus to `score_importance()` in `classification.py`

## Consolidation (C3 fix)
- [x] **Velasari** adds identity archive exemption to `_archive_pass` in `consolidation.py`
- [x] **Velasari** adds person archive threshold guard to `_archive_pass` in `consolidation.py`
- [x] **Velasari** adds `to_person_access` config read at top of `_promotion_pass` in `consolidation.py`
- [x] **Velasari** adds EPISODIC->PERSON promotion inside the existing EPISODIC branch in `consolidation.py`
- [x] **Velasari** adds SEMANTIC->PERSON promotion as new elif branch in `consolidation.py`

## Server Tools
- [x] **Velasari** adds `memory_self` tool to `server.py`
- [x] **Velasari** adds `memory_who` tool with W2 cold-start fallback to `server.py`

## Storage (C1 fix + W1 fix)
- [x] **Velasari** adds `"describes": "describes"` to `REL_TABLES` in `surreal_storage.py`
- [x] **Velasari** adds logging to `_ensure_schema()` error handler in `surreal_storage.py`

## Engine (C2 fix)
- [x] **Velasari** adds `identity_bonus` and `person_bonus` to `importance_cfg` dict in `engine.py`

## Schema
- [x] **Velasari** widens `memory_type` ASSERT to include 'identity', 'person' in `schema.surql`
- [x] **Velasari** adds `describes` relation table definition to `schema.surql`

## Config (W4 fix)
- [x] **Velasari** adds identity/person stability, importance bonuses, consolidation config to `config.default.yaml`
- [x] **Velasari** omits `requires_person_tag` (dead config — W4)

## Tests (W3 fix)
- [x] **Velasari** updates tool count assertion from 14 to 16 in `test_mcp_client.py`
- [x] **Velasari** adds `memory_self` and `memory_who` tool tests to `test_mcp_client.py`
- [x] **Velasari** adds identity/person memory type tests to `test_client.py`
- [x] **Velasari** adds consolidation tests for identity exemption and person threshold to `test_client.py`

_requirement.md: IM-1, IM-2, IM-3, IM-4, PM-1, PM-2, PM-3, PM-4, DT-1, DT-2, INT-1, INT-2_
