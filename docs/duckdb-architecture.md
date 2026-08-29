# DuckDB Data Model and Query Execution

AnswerCoalesce uses a read-only DuckDB database built from KGX node and edge
JSONL files. The database is not a general-purpose copy of the source graph.
It is organized specifically to support:

- Set-input graph enrichment
- EDGAR inference built on top of enrichment
- Retrieval of source provenance for returned support edges

This document describes the final database, the enrichment calculation, and
the additional steps performed by EDGAR.

## Database Overview

The final database contains twelve tables:

| Table | Purpose |
|---|---|
| `node` | Maps graph CURIEs to compact internal IDs and stores names and categories |
| `relation` | Stores each distinct predicate and qualifier combination |
| `relation_implication` | Maps concrete source relations to relationships implied by Biolink |
| `relation_hierarchy` | Records strict descendant-to-ancestor relationships between query-visible relations |
| `fact` | Stores each distinct semantic subject-relation-object edge |
| `evidence` | Stores the original edge IDs and source provenance behind each fact |
| `feature` | Defines reusable neighbor-relation-direction graph patterns |
| `feature_hierarchy` | Maps specific features to broader features for the same neighbor and direction |
| `membership` | Records which nodes possess which features |
| `category_count` | Stores the total number of nodes in each Biolink category |
| `feature_stats` | Stores feature background counts for each Biolink category |
| `metadata` | Identifies the database schema and records basic build counts |

The builder also uses temporary `raw_node`, `raw_edge`,
`raw_relation_implication`, and `raw_relation_hierarchy` staging tables. Those
tables are dropped before the final database is published.

The central distinction is:

```text
fact/evidence: preserve concrete graph edges and their source provenance

feature/membership/feature_stats:
    include concrete and Biolink-implied relationships for fast enrichment
```

## Node

The `node` table contains one row per retained graph node:

| Column | Meaning |
|---|---|
| `node_id` | Compact, release-local integer identifier |
| `curie` | External graph identifier |
| `name` | Display name |
| `categories` | Array of Biolink categories supplied by the source node record |

Example:

| node_id | curie | name | categories |
|---:|---|---|---|
| 1 | `CHEBI:10` | (+)-Atherospermoline | SmallMolecule, ChemicalEntity, NamedThing |
| 230571 | `ENSEMBL:ENSG00000064489` | ENSG00000064489 | Gene, GeneOrGeneProduct, NamedThing |
| 229029 | `DOID:0040002` | aspirin allergy | Disease, DiseaseOrPhenotypicFeature, NamedThing |

The integer ID reduces the size of joins and repeated references. It is not a
stable external identifier and may change between graph releases.

The category list is used directly by query-time category filtering and
background counting. The builder does not calculate missing category
ancestors. Its behavior therefore depends on how completely the source KGX
node categories were expanded.

Only the node ID, name, and categories are retained. Other KGX node properties,
such as synonyms, xrefs, descriptions, and publications, are not currently
stored.

## Relation

The `relation` table contains one row for each concrete or implied combination
of a Biolink predicate and its qualifiers:

| Column | Meaning |
|---|---|
| `relation_id` | Compact internal identifier |
| `predicate_json` | Complete predicate and qualifier signature |
| `predicate` | Base Biolink predicate |
| `is_symmetric` | Whether BMT reports the predicate as symmetric |

A simple signature is:

```json
{"predicate": "biolink:treats"}
```

A qualified signature can be:

```json
{
  "predicate": "biolink:affects",
  "qualified_predicate": "biolink:causes",
  "causal_mechanism_qualifier": "activation",
  "object_aspect_qualifier": "activity",
  "object_direction_qualifier": "increased",
  "species_context_qualifier": "NCBITaxon:10029"
}
```

Storing a relation once prevents the same JSON signature from being repeated
on millions of rows. `fact` and `feature` refer to it using `relation_id`.

The symmetry flag controls whether an edge can be followed in either
direction. It is calculated by BMT during the build.

## Relation Implication

The `relation_implication` table contains:

| Column | Meaning |
|---|---|
| `concrete_relation_id` | Relation present on the original KGX edge |
| `implied_relation_id` | Concrete or broader relation implied by Biolink |

Every concrete relation maps to itself. The builder also reproduces the
historical ORION redundant-edge transformation:

- Add every ancestor of the base predicate, without aspect, direction, or
  `qualified_predicate`
- Add every ancestor of `object_aspect_qualifier`
- Add every ancestor of `object_direction_qualifier`
- Add the direction-free form of a direction-qualified relation
- Add the fully unqualified base relation when an aspect qualifier is present

Other qualifiers remain attached unless the historical transformation
explicitly removed them. In particular, species context is retained.
`qualified_predicate` and species context are not themselves expanded.

## Relation Hierarchy

The `relation_hierarchy` table contains:

| Column | Meaning |
|---|---|
| `descendant_relation_id` | A more specific query-visible relation |
| `ancestor_relation_id` | A broader relation implied by the descendant |

The table contains strict ancestry only, so a relation does not map to itself.
It covers both base-predicate ancestry and the aspect and direction qualifier
ancestry materialized by the historical ORION transformation.

This table is used only for result selection. The application caches its
compact integer pairs and uses them to remove broader or narrower redundant
enrichments before linked-member lists are constructed. It does not create
evidence and does not alter the concrete `fact`/`evidence` model.

## Fact

The `fact` table stores distinct concrete semantic graph edges:

| Column | Meaning |
|---|---|
| `fact_id` | Internal fact identifier |
| `subject_node_id` | Subject node |
| `object_node_id` | Object node |
| `relation_id` | Predicate and qualifier signature |

Example:

| fact_id | subject_node_id | object_node_id | relation_id |
|---:|---:|---:|---:|
| 1 | 1 | 33155 | 20051 |
| 2 | 1 | 125452 | 20051 |
| 3 | 1 | 129972 | 20051 |

A fact is unique by:

```text
subject node + relation signature + object node
```

If multiple source records make the same semantic assertion, they share one
fact row and have separate rows in `evidence`.

## Evidence

The `evidence` table records the source records supporting each fact:

| Column | Meaning |
|---|---|
| `evidence_id` | Internal evidence identifier |
| `original_edge_id` | Edge ID from the source KGX file |
| `fact_id` | Semantic fact supported by this record |
| `sources_json` | Translator or ROBOKOP knowledge-source provenance |

For example, one evidence row may preserve:

```json
[
  {
    "resource_id": "infores:mgi",
    "resource_role": "primary_knowledge_source"
  },
  {
    "resource_id": "infores:agrkb",
    "resource_role": "aggregator_knowledge_source",
    "upstream_resource_ids": ["infores:mgi"]
  }
]
```

Every loaded edge must have exactly one primary knowledge source. The builder
fails rather than accepting missing or ambiguous primary provenance.

This table does not preserve the complete original KGX edge record. It retains:

- Original edge ID
- Subject, object, predicate, and qualifiers through `fact` and `relation`
- Knowledge-source provenance

Other edge properties, including publications, `knowledge_level`,
`agent_type`, descriptions, and arbitrary custom attributes, are currently
discarded.

## Feature

The `feature` table is derived from `fact` and `relation_implication`. It
contains each distinct concrete or implied graph pattern of:

```text
neighbor node + relation + direction
```

Its columns are:

| Column | Meaning |
|---|---|
| `feature_id` | Internal feature identifier |
| `neighbor_node_id` | The node at the other end of the pattern |
| `relation_id` | Predicate and qualifier signature |
| `member_is_subject` | Whether a node possessing this feature is the edge subject |

For example:

```text
neighbor = CHEBI:10022
relation = biolink:has_part
member_is_subject = true
```

represents:

```text
member node --has_part--> CHEBI:10022
```

If `member_is_subject` is false, it represents:

```text
neighbor node --relation--> member node
```

For symmetric predicates, direction is normalized because either endpoint can
be treated as the subject.

A feature is not an original KG entity or property. It is an internal
enrichment key shared by all nodes participating in the same graph pattern.
Its relation can be broader than the concrete relation on the source fact.

## Feature Hierarchy

The `feature_hierarchy` table materializes relation ancestry in feature space:

| Column | Meaning |
|---|---|
| `descendant_feature_id` | A feature using a more specific relation |
| `ancestor_feature_id` | The corresponding broader feature for the same neighbor and direction |

EDGAR uses this table to suppress implied ancestors of explicitly excluded
predicates without repeatedly joining the expanded membership set to itself.

## Membership

The `membership` table contains only:

| Column | Meaning |
|---|---|
| `member_node_id` | A graph node |
| `feature_id` | A feature possessed by that node |

Example:

| member_node_id | feature_id |
|---:|---:|
| 1 | 39138 |
| 1 | 167645 |
| 1 | 172337 |

After decoding the node and feature, one row might mean:

```text
CHEBI:10 --subclass_of--> CHEBI:133004
```

Conceptually, `membership` is an inverted graph index:

```text
node -> features possessed by the node
```

An enrichment query starts by retrieving the memberships of its input nodes
and counting how many inputs share each feature.

Membership is deduplicated after relation expansion. If several concrete facts
between the same nodes imply the same broader relation, the member contributes
only once to that implied feature.

## Category Count

The `category_count` table stores:

| Column | Meaning |
|---|---|
| `category_id` | Internal category identifier |
| `category` | Biolink category |
| `node_count` | Number of nodes whose stored categories include it |

For example:

```text
biolink:Gene -> total number of gene nodes
biolink:Disease -> total number of disease nodes
biolink:NamedThing -> total number of named-thing nodes
```

These counts overlap. A gene can also be counted as a
`biolink:BiologicalEntity` and `biolink:NamedThing`.

The input category's count supplies the enrichment background denominator.

## Feature Statistics

The `feature_stats` table stores:

| Column | Meaning |
|---|---|
| `category_id` | Input population category |
| `feature_id` | Feature being counted |
| `background_count` | Number of category members possessing the feature |

For example:

```text
category = biolink:Gene
feature = gene --expressed_in--> liver
background_count = 24,857
```

means that 24,857 nodes whose stored categories include `biolink:Gene` possess
the liver-expression feature.

If a feature has one member, it receives one `feature_stats` row with a count
of one for every category explicitly listed on that member.

The table contains precomputed background counts only. Query-specific support
counts and p-values are calculated at runtime.

## Metadata

The current metadata table records:

| Key | Meaning |
|---|---|
| `schema_version` | Database layout version expected by the application |
| `node_count` | Number of retained nodes |
| `raw_edge_count` | Number of retained source edge records |

`schema_version` identifies the storage layout, not the graph release.

The artifact does not yet record its graph release, build timestamp, source
checksums, Biolink version, BMT version, builder commit, or blocklist version.
This is tracked in
[issue 145](https://github.com/ranking-agent/AnswerCoalesce/issues/145).

## Set-Input Enrichment

A set-input query supplies:

- A set node with `set_interpretation: MANY`
- The member CURIEs
- The input Biolink category
- The desired output category
- A predicate and optional qualifiers
- An optional p-value threshold and result limit

The query flow is:

```text
TRAPI set query
    -> input node IDs
    -> memberships
    -> shared features
    -> support counts
    -> background comparison
    -> p-values
    -> selected enrichments
    -> provenance hydration
    -> TRAPI results
```

### 1. Parse and resolve the input

The input CURIEs are deduplicated and resolved to internal node IDs. The input
category is resolved through `category_count`.

The supplied number of distinct input CURIEs is used as the sample size. Only
CURIEs present in `node` can contribute membership support.

### 2. Select eligible features

DuckDB retrieves all `membership` rows for the input node IDs and materializes
that bounded subset once.

It joins those memberships to `feature`, `relation`, and the neighbor `node`.
Features are filtered by:

- Requested predicate and qualifiers
- Requested output category
- The AnswerCoalesce node blocklist

An unqualified predicate constraint matches stored relation signatures with the
same base predicate, including qualified versions. A qualified constraint also
requires the specified qualifier values. Predicate and supported qualifier
hierarchies were expanded while the database was built, so a broad relation can
match memberships originating from more specific source edges without
query-time BMT traversal.

Node category hierarchy expansion is not currently performed. Category
matching depends on the categories already stored on graph nodes.

### 3. Count input support

The eligible membership rows are grouped by `feature_id`:

```text
support_count = number of input nodes possessing the feature
```

Because membership is deduplicated, one input node contributes at most once to
a particular feature.

### 4. Calculate expected support

For a feature:

```text
n = number of distinct supplied input CURIEs
N = number of nodes in the input category
b = number of category members possessing the feature

expected_count = b * n / N
```

`N` comes from `category_count`. `b` comes from `feature_stats`.

Features whose observed support is below the expected count are discarded.
AnswerCoalesce therefore tests overrepresentation, not depletion.

### 5. Calculate the p-value

AnswerCoalesce uses the upper tail of a Poisson distribution:

```text
p_value = P(X >= support_count | mean = expected_count)
```

The calculation is performed inside DuckDB through a vectorized Arrow
function.

### 6. Prune and select enrichment results

Candidates are filtered by the optional p-value threshold. For EDGAR queries,
DuckDB first returns an ordered, compact candidate window containing IDs,
counts, and p-values but no linked-member arrays. The application compares
candidates for the same neighbor and edge direction using the cached
`relation_hierarchy`:

- A descendant removes an ancestor when its p-value is equal or better.
- An ancestor removes a descendant only when its p-value is strictly better.
- Unrelated relations are retained independently.

If the window does not yet prove the requested top-K boundary, it is expanded
and scored again. Once the boundary is complete, the surviving candidates are
limited by `max_results`.

Only the selected feature IDs are then joined back to the bounded input
memberships to collect the exact input CURIEs supporting each result.

One neighbor can produce multiple enrichment results when it is reached
through different predicates, qualifiers, or directions.

### 7. Hydrate selected evidence

After selection, AnswerCoalesce retrieves:

- Neighbor names and categories from `node`
- Predicate and qualifiers from `relation`
- Supporting concrete facts reached through `relation_implication`
- Source provenance from `evidence`

This hydration is batched. It is not performed once per result.

### 8. Construct the TRAPI response

For each enrichment, AnswerCoalesce creates:

- The enriched node
- Direct support edges between input members and the enriched node
- `member_of` edges connecting members to the set UUID
- Auxiliary graphs containing the direct and membership edges
- An inferred edge connecting the set UUID to the enriched node
- The enrichment p-value and a score derived from that p-value

No EDGAR second lookup occurs for a set-input query.

## Set-Input DuckDB Query Count

A normal successful set-input request executes eight data queries:

| Query | Purpose |
|---:|---|
| 1 | Retrieve the input category count |
| 2 | Resolve input CURIEs to node IDs |
| 3 | Load relation signatures and identify matching relations |
| 4 | Perform membership filtering, support counting, scoring, top-K selection, and linked-member construction |
| 5 | Retrieve selected neighbor names |
| 6 | Resolve selected relation signatures for provenance |
| 7 | Resolve support-edge CURIEs to node IDs |
| 8 | Retrieve fact and evidence provenance |

The relation-signature list is cached per worker thread. A warm worker can
therefore execute seven data queries.

The fourth query performs nearly all enrichment computation in one SQL
statement. The eighth query retrieves provenance for all selected support
edges in one batch. The query count does not increase with the number of input
members or returned results.

Opening a new worker-thread connection also performs schema validation and
DuckDB configuration statements. Those are connection setup rather than graph
queries.

## EDGAR Inference

EDGAR answers a single-node inferred query by constructing a set, enriching
that set, and applying the resulting enrichment rules to find new candidates.

For example:

```text
Wilson's disease
    -> directly associated genes
    -> enriched pathways, processes, diseases, or properties
    -> other genes matching those enrichment rules
    -> ranked inferred genes
```

### 1. Direct lookup

EDGAR first retrieves directly known answers for the bound input node, query
predicate, and requested output category.

For a Wilson's disease gene query, these known genes become the seed set. They
are retained as evidence but excluded from the final inferred candidates.

The initial lookup currently matches the base predicate. Query qualifiers are
not applied to this direct lookup.

### 2. Enrich the known answers

The seed set is passed through the same graph enrichment calculation described
above.

Graph enrichment and property enrichment run concurrently. Property
enrichment currently uses the separate property SQLite databases.

EDGAR can apply predicate, node, property, and p-value constraints. It removes
the original input and direct answers from the enrichment results and retains
the best `max_rules` rules. The default is 100.

Each graph enrichment becomes a rule such as:

```text
Genes connected to pathway P through relation R may be relevant.
```

The enrichment p-value measures the strength of that rule.

### 3. Apply graph rules

For every graph rule, AnswerCoalesce finds other nodes of the requested output
category connected to the enriched node through the same relation and
direction.

The implementation:

1. Resolves each rule's enriched node and matching relation signatures.
2. Retrieves the bounded membership slice for those enriched nodes.
3. Filters candidate neighbors by output category and direction.
4. Counts the evidence records supporting each candidate-rule match.
5. Produces a compact score contribution for each candidate.

This work is performed in bounded batches. Known direct answers are excluded.

### 4. Apply property rules

For each property enrichment, AnswerCoalesce retrieves other output-category
nodes possessing that property.

Graph and property candidates are then combined into one ranking.

### 5. Combine rule contributions

Each enrichment p-value is first transformed to a bounded weight. The EDGAR
scoring method treats matching rules as parallel conductances:

```text
conductance(rule) = -1 / log(transformed p-value)

total_conductance(candidate) =
    sum of all matching graph and property rule conductances

score(candidate) = exp(-1 / total_conductance)
```

A candidate matching more or stronger rules receives a higher score.

Current scoring preserves provenance multiplicity. If a candidate-rule edge
has multiple evidence records, that rule contributes once per evidence record.
This matches the previous behavior in which provenance expansion created
multiple lookup links.

### 6. Rank before evidence hydration

DuckDB returns compact candidate summaries rather than complete edge and
provenance objects.

AnswerCoalesce combines graph and property contributions, ranks candidates,
and selects `max_results`. The default is 2,000.

Only selected candidates proceed to full evidence hydration. This prevents
large queries from constructing Python objects for every possible candidate.

### 7. Hydrate selected candidates

For the selected candidate IDs, AnswerCoalesce retrieves:

- Candidate names and categories
- Candidate-to-rule edges
- Predicate qualifiers
- Source provenance

Property matches are filtered to the same selected candidate set. Enrichment
rules that support no selected candidate are omitted from the response.

### 8. Construct the EDGAR explanation

Each final result is an inferred edge between the candidate and the original
bound node. Its support represents a path like:

```text
candidate
    -> enriched graph node or property
    -> set of directly known answers
    -> original input
```

The response includes:

- The original input node
- The directly known answer nodes
- A UUID set node representing those known answers
- Enrichment rule nodes or properties
- Candidate nodes
- Direct, membership, enrichment, and inferred edges
- Auxiliary graphs describing the support paths

The final result score combines all graph and property rules supporting that
candidate. Unused nodes, edges, and auxiliary graphs are pruned before the
response is returned.

## Current Limitations

- The database does not preserve arbitrary KGX node and edge attributes.
- Artifact metadata does not yet identify the graph release or build inputs.
- Category hierarchy expansion is not performed.
- Relation expansion intentionally follows the historical ORION behavior and
  does not expand `qualified_predicate` or species-context values.
- Category statistics depend on category expansion already present in the
  source KGX nodes.
- The initial EDGAR direct lookup matches the base predicate without applying
  query qualifiers.
- Property enrichment remains in separate SQLite databases rather than the
  DuckDB graph artifact.

## Implementation Entry Points

- Database build: `src/graph_coalescence/build_duckdb.py`
- DuckDB queries: `src/graph_coalescence/duckdb_store.py`
- Graph enrichment orchestration: `src/graph_coalescence/graph_coalescer.py`
- MCQ and EDGAR orchestration: `src/single_node_coalescer.py`
- TRAPI construction: `src/trapi.py`
