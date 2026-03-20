-- Cognitive Memory SurrealDB Schema
-- Applied on first startup via SurrealStorage._ensure_schema()

-- Memory records
DEFINE TABLE memory SCHEMAFULL;
DEFINE FIELD content         ON memory TYPE string;
DEFINE FIELD memory_type     ON memory TYPE string ASSERT $value IN ['working', 'episodic', 'semantic', 'procedural'];
DEFINE FIELD state           ON memory TYPE string DEFAULT 'active' ASSERT $value IN ['active', 'archived'];
DEFINE FIELD importance      ON memory TYPE float ASSERT $value >= 0.0 AND $value <= 1.0;
DEFINE FIELD stability       ON memory TYPE float;
DEFINE FIELD retrievability  ON memory TYPE float;
DEFINE FIELD access_count    ON memory TYPE int DEFAULT 0;
DEFINE FIELD created_at      ON memory TYPE datetime;
DEFINE FIELD updated_at      ON memory TYPE datetime;
DEFINE FIELD last_accessed   ON memory TYPE datetime;
DEFINE FIELD source          ON memory TYPE option<string>;
DEFINE FIELD conversation_id ON memory TYPE option<string>;
DEFINE FIELD tags            ON memory TYPE array<string> DEFAULT [];
DEFINE FIELD embedding       ON memory TYPE option<array<float>>;

-- Vector index (HNSW, cosine distance, 384 dimensions for all-MiniLM-L6-v2)
DEFINE INDEX idx_memory_embedding ON memory FIELDS embedding HNSW DIMENSION 384 DIST COSINE;

-- Full-text search index
DEFINE ANALYZER memory_analyzer TOKENIZERS blank, class FILTERS lowercase, snowball(english);
DEFINE INDEX idx_memory_fts ON memory FIELDS content SEARCH ANALYZER memory_analyzer BM25;

-- Standard indexes
DEFINE INDEX idx_memory_state ON memory FIELDS state;
DEFINE INDEX idx_memory_type ON memory FIELDS memory_type;
DEFINE INDEX idx_memory_state_type ON memory FIELDS state, memory_type;

-- Graph edge tables (one per relationship type)
DEFINE TABLE causes SCHEMAFULL TYPE RELATION FROM memory TO memory;
DEFINE FIELD strength   ON causes TYPE float DEFAULT 1.0;
DEFINE FIELD created_at ON causes TYPE datetime;

DEFINE TABLE follows SCHEMAFULL TYPE RELATION FROM memory TO memory;
DEFINE FIELD strength   ON follows TYPE float DEFAULT 1.0;
DEFINE FIELD created_at ON follows TYPE datetime;

DEFINE TABLE contradicts SCHEMAFULL TYPE RELATION FROM memory TO memory;
DEFINE FIELD strength   ON contradicts TYPE float DEFAULT 1.0;
DEFINE FIELD created_at ON contradicts TYPE datetime;

DEFINE TABLE supports SCHEMAFULL TYPE RELATION FROM memory TO memory;
DEFINE FIELD strength   ON supports TYPE float DEFAULT 1.0;
DEFINE FIELD created_at ON supports TYPE datetime;

DEFINE TABLE relates_to SCHEMAFULL TYPE RELATION FROM memory TO memory;
DEFINE FIELD strength   ON relates_to TYPE float DEFAULT 1.0;
DEFINE FIELD created_at ON relates_to TYPE datetime;

DEFINE TABLE supersedes SCHEMAFULL TYPE RELATION FROM memory TO memory;
DEFINE FIELD strength   ON supersedes TYPE float DEFAULT 1.0;
DEFINE FIELD created_at ON supersedes TYPE datetime;

DEFINE TABLE part_of SCHEMAFULL TYPE RELATION FROM memory TO memory;
DEFINE FIELD strength   ON part_of TYPE float DEFAULT 1.0;
DEFINE FIELD created_at ON part_of TYPE datetime;

-- Memory versions
DEFINE TABLE memory_version SCHEMAFULL;
DEFINE FIELD memory_id  ON memory_version TYPE record<memory>;
DEFINE FIELD content     ON memory_version TYPE string;
DEFINE FIELD metadata    ON memory_version TYPE option<object>;
DEFINE FIELD created_at  ON memory_version TYPE datetime;
DEFINE INDEX idx_version_memory ON memory_version FIELDS memory_id;

-- Consolidation log
DEFINE TABLE consolidation_log SCHEMAFULL;
DEFINE FIELD action     ON consolidation_log TYPE string ASSERT $value IN ['promote', 'merge', 'archive', 'flag_contradiction'];
DEFINE FIELD source_ids ON consolidation_log TYPE array<string>;
DEFINE FIELD target_id  ON consolidation_log TYPE option<string>;
DEFINE FIELD reason     ON consolidation_log TYPE string;
DEFINE FIELD created_at ON consolidation_log TYPE datetime;

-- Config (keyed by record ID, e.g., preference:⟨decay.growth_factor⟩)
DEFINE TABLE preference SCHEMAFULL;
DEFINE FIELD val        ON preference TYPE any;
DEFINE FIELD updated_at ON preference TYPE datetime;
