-- Cognitive Memory SurrealDB Schema
-- Applied on first startup via SurrealStorage._ensure_schema()

-- Memory records
DEFINE TABLE OVERWRITE memory SCHEMAFULL;
DEFINE FIELD OVERWRITE content         ON memory TYPE string;
DEFINE FIELD OVERWRITE memory_type     ON memory TYPE string ASSERT $value IN ['working', 'episodic', 'semantic', 'procedural', 'identity', 'person'];
DEFINE FIELD OVERWRITE state           ON memory TYPE string DEFAULT 'active' ASSERT $value IN ['active', 'archived'];
DEFINE FIELD OVERWRITE importance      ON memory TYPE float ASSERT $value >= 0.0 AND $value <= 1.0;
DEFINE FIELD OVERWRITE stability       ON memory TYPE float;
DEFINE FIELD OVERWRITE retrievability  ON memory TYPE float;
DEFINE FIELD OVERWRITE access_count    ON memory TYPE int DEFAULT 0;
DEFINE FIELD OVERWRITE created_at      ON memory TYPE datetime;
DEFINE FIELD OVERWRITE updated_at      ON memory TYPE datetime;
DEFINE FIELD OVERWRITE last_accessed   ON memory TYPE datetime;
DEFINE FIELD OVERWRITE source          ON memory TYPE option<string>;
DEFINE FIELD OVERWRITE conversation_id ON memory TYPE option<string>;
DEFINE FIELD OVERWRITE tags            ON memory TYPE array<string> DEFAULT [];
DEFINE FIELD OVERWRITE embedding       ON memory TYPE option<array<float>>;

-- Vector index (HNSW, cosine distance, 384 dimensions for all-MiniLM-L6-v2)
DEFINE INDEX OVERWRITE idx_memory_embedding ON memory FIELDS embedding HNSW DIMENSION 384 DIST COSINE;

-- Full-text search index
DEFINE ANALYZER OVERWRITE memory_analyzer TOKENIZERS blank, class FILTERS lowercase, snowball(english);
DEFINE INDEX OVERWRITE idx_memory_fts ON memory FIELDS content SEARCH ANALYZER memory_analyzer BM25;

-- Standard indexes
DEFINE INDEX OVERWRITE idx_memory_state ON memory FIELDS state;
DEFINE INDEX OVERWRITE idx_memory_type ON memory FIELDS memory_type;
DEFINE INDEX OVERWRITE idx_memory_state_type ON memory FIELDS state, memory_type;

-- Graph edge tables (one per relationship type)
DEFINE TABLE OVERWRITE causes SCHEMAFULL TYPE RELATION FROM memory TO memory;
DEFINE FIELD OVERWRITE strength   ON causes TYPE float DEFAULT 1.0;
DEFINE FIELD OVERWRITE created_at ON causes TYPE datetime;

DEFINE TABLE OVERWRITE follows SCHEMAFULL TYPE RELATION FROM memory TO memory;
DEFINE FIELD OVERWRITE strength   ON follows TYPE float DEFAULT 1.0;
DEFINE FIELD OVERWRITE created_at ON follows TYPE datetime;

DEFINE TABLE OVERWRITE contradicts SCHEMAFULL TYPE RELATION FROM memory TO memory;
DEFINE FIELD OVERWRITE strength   ON contradicts TYPE float DEFAULT 1.0;
DEFINE FIELD OVERWRITE created_at ON contradicts TYPE datetime;

DEFINE TABLE OVERWRITE supports SCHEMAFULL TYPE RELATION FROM memory TO memory;
DEFINE FIELD OVERWRITE strength   ON supports TYPE float DEFAULT 1.0;
DEFINE FIELD OVERWRITE created_at ON supports TYPE datetime;

DEFINE TABLE OVERWRITE relates_to SCHEMAFULL TYPE RELATION FROM memory TO memory;
DEFINE FIELD OVERWRITE strength   ON relates_to TYPE float DEFAULT 1.0;
DEFINE FIELD OVERWRITE created_at ON relates_to TYPE datetime;

DEFINE TABLE OVERWRITE supersedes SCHEMAFULL TYPE RELATION FROM memory TO memory;
DEFINE FIELD OVERWRITE strength   ON supersedes TYPE float DEFAULT 1.0;
DEFINE FIELD OVERWRITE created_at ON supersedes TYPE datetime;

DEFINE TABLE OVERWRITE part_of SCHEMAFULL TYPE RELATION FROM memory TO memory;
DEFINE FIELD OVERWRITE strength   ON part_of TYPE float DEFAULT 1.0;
DEFINE FIELD OVERWRITE created_at ON part_of TYPE datetime;

DEFINE TABLE OVERWRITE describes SCHEMAFULL TYPE RELATION FROM memory TO memory;
DEFINE FIELD OVERWRITE strength   ON describes TYPE float DEFAULT 1.0;
DEFINE FIELD OVERWRITE created_at ON describes TYPE datetime;

-- Memory versions
DEFINE TABLE OVERWRITE memory_version SCHEMAFULL;
DEFINE FIELD OVERWRITE memory_id  ON memory_version TYPE record<memory>;
DEFINE FIELD OVERWRITE content     ON memory_version TYPE string;
DEFINE FIELD OVERWRITE metadata    ON memory_version TYPE option<object>;
DEFINE FIELD OVERWRITE created_at  ON memory_version TYPE datetime;
DEFINE INDEX OVERWRITE idx_version_memory ON memory_version FIELDS memory_id;

-- Consolidation log
DEFINE TABLE OVERWRITE consolidation_log SCHEMAFULL;
DEFINE FIELD OVERWRITE action     ON consolidation_log TYPE string ASSERT $value IN ['promote', 'merge', 'archive', 'flag_contradiction'];
DEFINE FIELD OVERWRITE source_ids ON consolidation_log TYPE array<string>;
DEFINE FIELD OVERWRITE target_id  ON consolidation_log TYPE option<string>;
DEFINE FIELD OVERWRITE reason     ON consolidation_log TYPE string;
DEFINE FIELD OVERWRITE created_at ON consolidation_log TYPE datetime;

-- Config (keyed by record ID, e.g., preference:⟨decay.growth_factor⟩)
DEFINE TABLE OVERWRITE preference SCHEMAFULL;
DEFINE FIELD OVERWRITE val        ON preference TYPE any;
DEFINE FIELD OVERWRITE updated_at ON preference TYPE datetime;
