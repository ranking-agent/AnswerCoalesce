import json
import os
import threading
from dataclasses import dataclass
from pathlib import Path

import duckdb
import orjson
import pyarrow
from duckdb.sqltypes import BIGINT, DOUBLE
from scipy.special import pdtrc

from src.scoring import pvalue_to_conductance

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_QUERY_MEMORY_LIMIT = "1GB"
DEFAULT_QUERY_MAX_TEMP_DIRECTORY_SIZE = "8GB"
DEFAULT_QUERY_THREADS = 2
DEFAULT_INFERENCE_RULE_BATCH_SIZE = 100
DEFAULT_HIERARCHY_CANDIDATE_WINDOW = 1_000
EXPECTED_SCHEMA_VERSION = "7"
BLOCKLIST = {
    "HP:0000118",
    "MONDO:0000001",
    "MONDO:0700096",
    "UMLS:C1333305",
    "CHEBI:24431",
    "CHEBI:23367",
    "CHEBI:33579",
    "CHEBI:36357",
    "CHEBI:33675",
    "CHEBI:33302",
    "CHEBI:33304",
    "CHEBI:33582",
    "CHEBI:25806",
    "CHEBI:50860",
    "CHEBI:51143",
    "CHEBI:32988",
    "CHEBI:33285",
    "CHEBI:33256",
    "CHEBI:36962",
    "CHEBI:35352",
    "CHEBI:36963",
    "CHEBI:25367",
    "CHEBI:72695",
    "CHEBI:33595",
    "CHEBI:33832",
    "CHEBI:37577",
    "CHEBI:24532",
    "CHEBI:5686",
    "NCBITaxon:9606",
}

_thread_state = threading.local()
_udf_lock = threading.Lock()
_connection_lock = threading.Lock()
_configured_temp_directories = {}


@dataclass(frozen=True)
class EnrichmentCandidate:
    neighbor_curie: str
    predicate_json: str
    member_is_subject: bool
    is_symmetric: bool
    p_value: float
    support_count: int
    background_count: int
    linked_curies: tuple[str, ...]
    neighbor_categories: tuple[str, ...]


@dataclass(frozen=True)
class GraphInferenceSummary:
    inferred_curie: str
    total_conductance: float
    inference_count: int
    first_seen_order: int


def database_path():
    configured_path = os.getenv("AC_DUCKDB_PATH")
    if not configured_path:
        with open(PROJECT_ROOT / "config.json", encoding="utf-8") as stream:
            configured_path = json.load(stream)["duckdb_path"]
    path = Path(configured_path)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.resolve()


def _poisson_survival(support_count, expected_count):
    return pyarrow.array(
        pdtrc(
            support_count.to_numpy(zero_copy_only=False) - 1,
            expected_count.to_numpy(zero_copy_only=False),
        )
    )


def connection():
    path = database_path()
    if not path.is_file():
        raise FileNotFoundError(
            f"AnswerCoalesce DuckDB database not found at {path}. "
            "Set AC_DUCKDB_PATH or build the configured database."
        )
    cached_path = getattr(_thread_state, "path", None)
    cached_connection = getattr(_thread_state, "connection", None)
    if cached_connection is None or cached_path != path:
        if cached_connection is not None:
            cached_connection.close()
        cached_connection = duckdb.connect(str(path), read_only=True)
        schema_version = cached_connection.execute(
            "SELECT value FROM metadata WHERE key = 'schema_version'"
        ).fetchone()
        if schema_version is None or schema_version[0] != EXPECTED_SCHEMA_VERSION:
            cached_connection.close()
            _thread_state.connection = None
            _thread_state.path = None
            _thread_state.relation_rows = None
            _thread_state.relation_ancestor_ids = None
            found_version = schema_version[0] if schema_version else "missing"
            raise RuntimeError(
                f"AnswerCoalesce DuckDB schema version {found_version} is not "
                f"supported; expected {EXPECTED_SCHEMA_VERSION}. Rebuild the "
                "configured graph database."
            )
        temp_directory = os.getenv(
            "AC_DUCKDB_QUERY_TEMP_DIRECTORY",
            f"/tmp/answer-coalesce-duckdb-{os.getpid()}",
        )
        with _connection_lock:
            configured_temp_directory = _configured_temp_directories.get(path)
            if configured_temp_directory is None:
                cached_connection.execute(
                    "SET temp_directory = ?",
                    [temp_directory],
                )
                _configured_temp_directories[path] = temp_directory
            elif configured_temp_directory != temp_directory:
                cached_connection.close()
                raise RuntimeError(
                    "AC_DUCKDB_QUERY_TEMP_DIRECTORY cannot change while the "
                    f"database is open; using {configured_temp_directory}"
                )
        with _udf_lock:
            functions = {
                name
                for name, in cached_connection.execute(
                    """
                    SELECT function_name
                    FROM duckdb_functions()
                    WHERE function_name = 'ac_poisson_survival'
                    """
                ).fetchall()
            }
            if "ac_poisson_survival" not in functions:
                cached_connection.create_function(
                    "ac_poisson_survival",
                    _poisson_survival,
                    [BIGINT, DOUBLE],
                    DOUBLE,
                    type="arrow",
                )
        settings = {
            "memory_limit": os.getenv(
                "AC_DUCKDB_QUERY_MEMORY_LIMIT",
                DEFAULT_QUERY_MEMORY_LIMIT,
            ),
            "max_temp_directory_size": os.getenv(
                "AC_DUCKDB_QUERY_MAX_TEMP_DIRECTORY_SIZE",
                DEFAULT_QUERY_MAX_TEMP_DIRECTORY_SIZE,
            ),
            "threads": os.getenv(
                "AC_DUCKDB_QUERY_THREADS",
                str(DEFAULT_QUERY_THREADS),
            ),
            "preserve_insertion_order": "false",
        }
        for name, value in settings.items():
            cached_connection.execute(
                f"SET {name} = ?",
                [value],
            )
        _thread_state.path = path
        _thread_state.connection = cached_connection
        _thread_state.relation_rows = None
        _thread_state.relation_ancestor_ids = None
    return cached_connection


def close_connection():
    cached_connection = getattr(_thread_state, "connection", None)
    if cached_connection is not None:
        cached_connection.close()
    _thread_state.connection = None
    _thread_state.path = None
    _thread_state.relation_rows = None
    _thread_state.relation_ancestor_ids = None


def _normalized_constraint(constraint):
    if isinstance(constraint, dict):
        return constraint
    if isinstance(constraint, str) and constraint.startswith("{"):
        return orjson.loads(constraint)
    return {"predicate": constraint}


def _trapi_sources(provenance):
    if isinstance(provenance, list):
        return provenance
    return [
        {
            "resource_id": (
                ",".join(value) if isinstance(value, list) else value
            ),
            "resource_role": role.removeprefix("biolink:"),
        }
        for role, value in provenance.items()
    ]


def _relation_ids(predicate_constraints, style, context_qualifiers):
    constraints = [
        _normalized_constraint(constraint)
        for constraint in (predicate_constraints or [])
    ]
    if not constraints and not context_qualifiers:
        return None

    rows = getattr(_thread_state, "relation_rows", None)
    if rows is None:
        rows = connection().execute(
            "SELECT relation_id, predicate_json FROM relation"
        ).fetchall()
        _thread_state.relation_rows = rows
    matched = set()
    for relation_id, relation_json in rows:
        relation = orjson.loads(relation_json)
        context_matches = all(
            relation.get(key) == value
            for key, value in (context_qualifiers or {}).items()
        )
        constraint_matches = not constraints or any(
            constraint.items() <= relation.items() for constraint in constraints
        )
        if context_matches and constraint_matches:
            matched.add(relation_id)

    if style == "exclude" and constraints:
        context_ids = {
            relation_id
            for relation_id, relation_json in rows
            if all(
                orjson.loads(relation_json).get(key) == value
                for key, value in (context_qualifiers or {}).items()
            )
        }
        return context_ids - matched
    return matched


def _relation_ancestor_ids():
    cached = getattr(_thread_state, "relation_ancestor_ids", None)
    if cached is None:
        cached = {}
        for descendant_relation_id, ancestor_relation_id in connection().execute(
            """
            SELECT descendant_relation_id, ancestor_relation_id
            FROM relation_hierarchy
            ORDER BY descendant_relation_id, ancestor_relation_id
            """
        ).fetchall():
            cached.setdefault(descendant_relation_id, []).append(
                ancestor_relation_id
            )
        cached = {
            relation_id: tuple(ancestor_ids)
            for relation_id, ancestor_ids in cached.items()
        }
        _thread_state.relation_ancestor_ids = cached
    return cached


def _prune_hierarchy_candidate_rows(rows):
    """Remove statistically dominated ancestors or descendants."""
    candidate_by_relation = {
        (row[1], row[3], row[2]): row
        for row in rows
    }
    dominated_feature_ids = set()
    relation_ancestors = _relation_ancestor_ids()
    for descendant in rows:
        for ancestor_relation_id in relation_ancestors.get(
            descendant[2],
            (),
        ):
            ancestor = candidate_by_relation.get(
                (
                    descendant[1],
                    descendant[3],
                    ancestor_relation_id,
                )
            )
            if ancestor is None:
                continue
            if descendant[4] <= ancestor[4]:
                dominated_feature_ids.add(ancestor[0])
            if ancestor[4] < descendant[4]:
                dominated_feature_ids.add(descendant[0])
    return [
        row
        for row in rows
        if row[0] not in dominated_feature_ids
    ]


def get_node_types(curies):
    curies = list(dict.fromkeys(curies))
    if not curies:
        return {}
    rows = connection().execute(
        "SELECT curie, categories FROM node WHERE curie IN (SELECT unnest(?))",
        [curies],
    ).fetchall()
    return {curie: categories for curie, categories in rows}


def get_node_names(curies):
    curies = list(dict.fromkeys(curies))
    if not curies:
        return {}
    rows = connection().execute(
        "SELECT curie, name FROM node WHERE curie IN (SELECT unnest(?))",
        [curies],
    ).fetchall()
    return {curie: name or "" for curie, name in rows}


def get_total_node_counts(semantic_type):
    rows = connection().execute(
        """
        SELECT category, node_count
        FROM category_count
        WHERE category IN (?, 'biolink:NamedThing')
        """,
        [semantic_type],
    ).fetchall()
    counts = {category: float(count) for category, count in rows}
    if semantic_type not in counts and "biolink:NamedThing" in counts:
        counts[semantic_type] = counts["biolink:NamedThing"]
    return counts


def create_nodes_to_links(allnodes, param_predicates=None, neighbor_ids=None):
    unique_nodes = list(dict.fromkeys(allnodes))
    result = {node: [] for node in unique_nodes}
    if not unique_nodes:
        return result
    unique_neighbors = (
        list(dict.fromkeys(neighbor_ids))
        if neighbor_ids is not None
        else None
    )
    if unique_neighbors == []:
        return result

    current_connection = connection()
    node_rows = current_connection.execute(
        """
        SELECT node_id, curie
        FROM node
        WHERE curie IN (SELECT unnest(?))
        """,
        [unique_nodes],
    ).fetchall()
    node_curie_by_id = {
        node_id: curie
        for node_id, curie in node_rows
    }
    if not node_curie_by_id:
        return result

    neighbor_filter = ""
    query_params = [list(node_curie_by_id)]
    if unique_neighbors is not None:
        neighbor_filter = """
          AND neighbor.curie IN (SELECT unnest(?))
        """
        query_params.append(unique_neighbors)
    rows = current_connection.execute(
        f"""
        SELECT
            membership.member_node_id,
            neighbor.curie,
            relation.predicate_json,
            feature.member_is_subject,
            relation.is_symmetric
        FROM membership
        JOIN feature USING (feature_id)
        JOIN relation USING (relation_id)
        JOIN node neighbor ON neighbor.node_id = feature.neighbor_node_id
        WHERE membership.member_node_id IN (SELECT unnest(?))
          {neighbor_filter}
        """,
        query_params,
    ).fetchall()

    predicates_by_node = {}
    if param_predicates:
        for node, predicate in zip(allnodes, param_predicates):
            predicates_by_node.setdefault(node, []).append(_normalized_constraint(predicate))

    for (
        member_id,
        neighbor,
        relation_json,
        member_is_subject,
        is_symmetric,
    ) in rows:
        member = node_curie_by_id[member_id]
        constraints = predicates_by_node.get(member)
        if constraints:
            relation = orjson.loads(relation_json)
            if not any(constraint.items() <= relation.items() for constraint in constraints):
                continue
        result[member].append(
            [neighbor, relation_json, member_is_subject, is_symmetric]
        )
    return result


def graph_inference_summaries(rules, output_category, excluded_ids=None):
    """
    Aggregate EDGAR graph-rule contributions before hydrating edge evidence.

    Provenance multiplicity is retained because the existing inference scorer
    counts one contribution for each provenance-expanded lookup link.
    """
    if not rules:
        return []

    current_connection = connection()
    relation_rows = current_connection.execute(
        """
        SELECT relation_id, predicate_json, is_symmetric
        FROM relation
        """
    ).fetchall()
    node_ids = {
        curie: node_id
        for curie, node_id in current_connection.execute(
            """
            SELECT curie, node_id
            FROM node
            WHERE curie IN (SELECT unnest(?))
            """,
            [list(dict.fromkeys(rule["enriched_curie"] for rule in rules))],
        ).fetchall()
    }
    excluded_ids = list(dict.fromkeys(excluded_ids or []))

    batch_size = int(
        os.getenv(
            "AC_DUCKDB_INFERENCE_RULE_BATCH_SIZE",
            str(DEFAULT_INFERENCE_RULE_BATCH_SIZE),
        )
    )
    if batch_size <= 0:
        raise ValueError("AC_DUCKDB_INFERENCE_RULE_BATCH_SIZE must be positive")

    resolved_rules = {}
    for rule_position, rule in enumerate(rules):
        enriched_node_id = node_ids.get(rule["enriched_curie"])
        if enriched_node_id is None:
            continue
        constraint = _normalized_constraint(rule["predicate_json"])
        conductance = float(pvalue_to_conductance([rule["p_value"]])[0])
        for relation_id, relation_json, is_symmetric in relation_rows:
            relation = orjson.loads(relation_json)
            if constraint.items() <= relation.items():
                key = (
                    enriched_node_id,
                    relation_id,
                    bool(rule["is_source"]),
                )
                resolved_rules.setdefault(key, []).append(
                    {
                        "batch": rule_position // batch_size,
                        "rule_id": rule["rule_id"],
                        "enriched_node_id": enriched_node_id,
                        "relation_id": relation_id,
                        "is_symmetric": is_symmetric,
                        "is_source": bool(rule["is_source"]),
                        "conductance": conductance,
                    }
                )
    if not resolved_rules:
        return []

    membership_filter = ""
    query_params = [
        list(dict.fromkeys(key[0] for key in resolved_rules)),
        output_category,
    ]
    if excluded_ids:
        membership_filter = """
          AND candidate.curie NOT IN (SELECT unnest(?))
        """
        query_params.append(excluded_ids)
    candidate_rows = current_connection.execute(
        f"""
        WITH matched_membership AS MATERIALIZED (
            SELECT member_node_id, feature_id
            FROM membership
            WHERE member_node_id IN (SELECT unnest(?))
        )
        SELECT
            matched.member_node_id,
            feature.feature_id,
            feature.neighbor_node_id,
            feature.relation_id,
            feature.member_is_subject
        FROM matched_membership matched
        JOIN feature USING (feature_id)
        JOIN node candidate
          ON candidate.node_id = feature.neighbor_node_id
        WHERE list_contains(candidate.categories, ?)
          {membership_filter}
        ORDER BY matched.member_node_id, feature.feature_id
        """,
        query_params,
    ).fetchall()

    matches_by_batch = {}
    for (
        enriched_node_id,
        feature_id,
        candidate_node_id,
        relation_id,
        member_is_subject,
    ) in candidate_rows:
        for rule in resolved_rules.get(
            (enriched_node_id, relation_id, member_is_subject),
            (),
        ):
            matches_by_batch.setdefault(rule["batch"], []).append(
                {
                    **rule,
                    "feature_id": feature_id,
                    "candidate_node_id": candidate_node_id,
                }
            )

    summary_by_node_id = {}
    for matches in matches_by_batch.values():
        match_table = pyarrow.table(
            {
                "rule_id": [match["rule_id"] for match in matches],
                "enriched_node_id": [
                    match["enriched_node_id"] for match in matches
                ],
                "relation_id": [
                    match["relation_id"] for match in matches
                ],
                "is_symmetric": [
                    match["is_symmetric"] for match in matches
                ],
                "is_source": [match["is_source"] for match in matches],
                "conductance": [
                    match["conductance"] for match in matches
                ],
                "feature_id": [match["feature_id"] for match in matches],
                "candidate_node_id": [
                    match["candidate_node_id"] for match in matches
                ],
            }
        )
        current_connection.register("_graph_inference_matches", match_table)
        try:
            rows = current_connection.execute(
                """
                WITH
                resolved_facts AS (
                    SELECT
                        matched.rule_id,
                        matched.candidate_node_id,
                        matched.relation_id,
                        fact.fact_id
                    FROM _graph_inference_matches matched
                    JOIN relation_implication implication
                      ON implication.implied_relation_id
                         = matched.relation_id
                    JOIN fact
                      ON fact.relation_id
                         = implication.concrete_relation_id
                     AND fact.subject_node_id = matched.enriched_node_id
                     AND fact.object_node_id = matched.candidate_node_id
                    WHERE matched.is_source

                    UNION ALL

                    SELECT
                        matched.rule_id,
                        matched.candidate_node_id,
                        matched.relation_id,
                        fact.fact_id
                    FROM _graph_inference_matches matched
                    JOIN relation_implication implication
                      ON implication.implied_relation_id
                         = matched.relation_id
                    JOIN fact
                      ON fact.relation_id
                         = implication.concrete_relation_id
                     AND fact.subject_node_id = matched.candidate_node_id
                     AND fact.object_node_id = matched.enriched_node_id
                    WHERE NOT matched.is_source

                    UNION ALL

                    SELECT
                        matched.rule_id,
                        matched.candidate_node_id,
                        matched.relation_id,
                        fact.fact_id
                    FROM _graph_inference_matches matched
                    JOIN relation_implication implication
                      ON implication.implied_relation_id
                         = matched.relation_id
                    JOIN fact
                      ON fact.relation_id
                         = implication.concrete_relation_id
                     AND fact.subject_node_id = matched.candidate_node_id
                     AND fact.object_node_id = matched.enriched_node_id
                    WHERE matched.is_source
                      AND matched.is_symmetric
                      AND matched.candidate_node_id
                          != matched.enriched_node_id

                    UNION ALL

                    SELECT
                        matched.rule_id,
                        matched.candidate_node_id,
                        matched.relation_id,
                        fact.fact_id
                    FROM _graph_inference_matches matched
                    JOIN relation_implication implication
                      ON implication.implied_relation_id
                         = matched.relation_id
                    JOIN fact
                      ON fact.relation_id
                         = implication.concrete_relation_id
                     AND fact.subject_node_id = matched.enriched_node_id
                     AND fact.object_node_id = matched.candidate_node_id
                    WHERE NOT matched.is_source
                      AND matched.is_symmetric
                      AND matched.candidate_node_id
                          != matched.enriched_node_id
                ),
                evidence_counts AS (
                    SELECT
                        resolved.rule_id,
                        resolved.candidate_node_id,
                        resolved.relation_id,
                        count(evidence.evidence_id)::BIGINT AS evidence_count
                    FROM resolved_facts resolved
                    JOIN evidence USING (fact_id)
                    GROUP BY
                        resolved.rule_id,
                        resolved.candidate_node_id,
                        resolved.relation_id
                )
                SELECT
                    matched.candidate_node_id,
                    sum(
                        matched.conductance
                        * greatest(coalesce(evidence.evidence_count, 0), 1)
                    )::DOUBLE AS total_conductance,
                    sum(
                        greatest(coalesce(evidence.evidence_count, 0), 1)
                    )::BIGINT AS inference_count,
                    min(
                        matched.rule_id::BIGINT * 1000000000
                        + matched.feature_id
                    )::BIGINT AS first_seen_order
                FROM _graph_inference_matches matched
                LEFT JOIN evidence_counts evidence
                  ON evidence.rule_id = matched.rule_id
                 AND evidence.candidate_node_id
                     = matched.candidate_node_id
                 AND evidence.relation_id = matched.relation_id
                GROUP BY matched.candidate_node_id
                ORDER BY matched.candidate_node_id
                """
            ).fetchall()
        finally:
            current_connection.unregister("_graph_inference_matches")

        for node_id, conductance, count, first_seen_order in rows:
            previous = summary_by_node_id.get(node_id)
            if previous is None:
                summary_by_node_id[node_id] = [
                    conductance,
                    count,
                    first_seen_order,
                ]
            else:
                previous[0] += conductance
                previous[1] += count
                previous[2] = min(previous[2], first_seen_order)

    if not summary_by_node_id:
        return []
    curies = {
        node_id: curie
        for node_id, curie in current_connection.execute(
            """
            SELECT node_id, curie
            FROM node
            WHERE node_id IN (SELECT unnest(?))
            """,
            [list(summary_by_node_id)],
        ).fetchall()
    }
    return [
        GraphInferenceSummary(
            inferred_curie=curies[node_id],
            total_conductance=summary[0],
            inference_count=summary[1],
            first_seen_order=summary[2],
        )
        for node_id, summary in sorted(
            summary_by_node_id.items(),
            key=lambda item: curies[item[0]],
        )
    ]


def enrichment_candidates(
    input_ids,
    input_category,
    *,
    input_is_subject=None,
    node_constraints=None,
    predicate_constraints=None,
    predicate_constraint_style="exclude",
    context_qualifiers=None,
    hierarchy_exclusion_pairs=None,
    filter_predicate_hierarchies=False,
    exclude_ids=None,
    pvalue_threshold=None,
    max_results=None,
):
    input_ids = list(dict.fromkeys(input_ids))
    if not input_ids:
        return [], 0

    current_connection = connection()
    category_rows = current_connection.execute(
        """
        SELECT category_id, category, node_count
        FROM category_count
        WHERE category IN (?, 'biolink:NamedThing')
        """,
        [input_category],
    ).fetchall()
    categories = {
        category: (category_id, int(node_count))
        for category_id, category, node_count in category_rows
    }
    background_category = categories.get(input_category)
    if background_category is None:
        background_category = categories.get("biolink:NamedThing")
    if background_category is None:
        return [], 0
    background_category_id, total_node_count = background_category

    input_rows = current_connection.execute(
        """
        SELECT node_id, curie
        FROM node
        WHERE curie IN (SELECT unnest(?))
        """,
        [input_ids],
    ).fetchall()
    input_node_ids = [row[0] for row in input_rows]
    if not input_node_ids:
        return [], total_node_count

    matched_relation_ids = _relation_ids(
        predicate_constraints,
        predicate_constraint_style,
        context_qualifiers,
    )
    if matched_relation_ids == set():
        return [], total_node_count
    relation_ids = (
        sorted(matched_relation_ids)
        if matched_relation_ids is not None
        else None
    )

    hierarchy_exclusion_pairs = hierarchy_exclusion_pairs or []
    hierarchy_cte = ""
    hierarchy_join = ""
    hierarchy_filter = ""
    query_params = [input_node_ids]
    if hierarchy_exclusion_pairs:
        hierarchy_cte = """,
        excluded_predicates AS (
            SELECT unnest(?) AS predicate
        ),
        excluded_ancestor_membership AS MATERIALIZED (
            SELECT DISTINCT
                excluded_membership.member_node_id,
                hierarchy.ancestor_feature_id AS feature_id
            FROM matched_membership excluded_membership
            JOIN feature excluded_feature USING (feature_id)
            JOIN relation excluded_relation
              ON excluded_relation.relation_id = excluded_feature.relation_id
            JOIN excluded_predicates
              ON excluded_predicates.predicate = excluded_relation.predicate
            JOIN feature_hierarchy hierarchy
              ON hierarchy.descendant_feature_id
                 = excluded_membership.feature_id
        )
        """
        query_params.append(
            sorted(
                {
                    excluded_predicate
                    for excluded_predicate, _ in hierarchy_exclusion_pairs
                }
            )
        )
        hierarchy_filter = """
          AND NOT EXISTS (
              SELECT 1
              FROM excluded_ancestor_membership excluded
              WHERE excluded.member_node_id
                    = candidate_membership.member_node_id
                AND excluded.feature_id = candidate_membership.feature_id
          )
        """

    relation_filter = ""
    if relation_ids is not None:
        relation_filter = """
              AND feature.relation_id IN (SELECT unnest(?))
        """
        query_params.append(relation_ids)
    direction_join = ""
    direction_filter = ""
    if input_is_subject is not None:
        direction_join = """
            JOIN relation direction_relation
              ON direction_relation.relation_id = feature.relation_id
        """
        direction_filter = """
              AND (
                  direction_relation.is_symmetric
                  OR feature.member_is_subject = ?
              )
        """
        query_params.append(input_is_subject)
    query_params.extend(BLOCKLIST)
    exclude_filter = ""
    excluded_curies = list(dict.fromkeys(exclude_ids or ()))
    if excluded_curies:
        exclude_filter = """
              AND neighbor.curie NOT IN (SELECT unnest(?))
        """
        query_params.append(excluded_curies)
    category_filter = ""
    requested_categories = node_constraints or ["biolink:NamedThing"]
    if "biolink:NamedThing" not in requested_categories:
        category_filter = """
            AND EXISTS (
                SELECT 1
                FROM unnest(neighbor.categories) AS category_value(category)
                WHERE category IN (SELECT unnest(?))
            )
        """
        query_params.append(requested_categories)

    candidate_filter = ""
    if pvalue_threshold is not None:
        candidate_filter = "WHERE p_value < ?"

    eligibility_params = query_params
    scoring_params = [
        len(input_ids),
        total_node_count,
        background_category_id,
        len(input_ids),
        total_node_count,
    ]
    if pvalue_threshold is not None:
        scoring_params.append(pvalue_threshold)

    eligibility_ctes = f"""
        matched_membership AS MATERIALIZED (
            SELECT
                membership.member_node_id,
                membership.feature_id
            FROM membership
            WHERE membership.member_node_id IN (SELECT unnest(?))
        )
        {hierarchy_cte}
        ,
        eligible_membership AS MATERIALIZED (
            SELECT
                candidate_membership.member_node_id,
                candidate_membership.feature_id
            FROM matched_membership candidate_membership
            JOIN feature USING (feature_id)
            {direction_join}
            JOIN node neighbor ON neighbor.node_id = feature.neighbor_node_id
            {hierarchy_join}
            WHERE TRUE
              {relation_filter}
              {direction_filter}
              AND neighbor.curie NOT IN (
                {",".join("?" for _ in BLOCKLIST)}
            )
              {exclude_filter}
              {hierarchy_filter}
              {category_filter}
        )
    """
    scoring_ctes = """
        ,
        candidate_support AS (
            SELECT
                feature_id,
                count(*)::BIGINT AS support_count
            FROM eligible_membership
            GROUP BY feature_id
        ),
        surviving AS (
            SELECT
                candidate.feature_id,
                candidate.support_count,
                stats.background_count,
                ac_poisson_survival(
                    candidate.support_count,
                    stats.background_count * ?::DOUBLE / ?
                ) AS p_value
            FROM candidate_support candidate
            JOIN feature_stats stats
              ON stats.category_id = ?
             AND stats.feature_id = candidate.feature_id
            WHERE candidate.support_count >= stats.background_count * ? / ?
        )
    """

    if filter_predicate_hierarchies:
        candidate_window = (
            None
            if max_results is None
            else max(
                DEFAULT_HIERARCHY_CANDIDATE_WINDOW,
                max_results * 10,
            )
        )
        while True:
            window_limit = "LIMIT ?" if candidate_window is not None else ""
            compact_params = eligibility_params + scoring_params
            if candidate_window is not None:
                compact_params.append(candidate_window)
            compact_rows = current_connection.execute(
                f"""
                WITH
                {eligibility_ctes}
                {scoring_ctes}
                ,
                selected AS (
                    SELECT
                        surviving.feature_id,
                        feature.neighbor_node_id,
                        feature.relation_id,
                        feature.member_is_subject,
                        surviving.p_value,
                        surviving.support_count,
                        surviving.background_count
                    FROM surviving
                    JOIN feature USING (feature_id)
                    {candidate_filter}
                    ORDER BY
                        surviving.p_value,
                        feature.neighbor_node_id,
                        feature.relation_id,
                        feature.member_is_subject,
                        surviving.feature_id
                    {window_limit}
                )
                SELECT
                    selected.feature_id,
                    selected.neighbor_node_id,
                    selected.relation_id,
                    selected.member_is_subject,
                    selected.p_value,
                    selected.support_count,
                    selected.background_count,
                    neighbor.curie,
                    relation.predicate_json,
                    relation.is_symmetric,
                    neighbor.categories
                FROM selected
                JOIN relation
                  ON relation.relation_id = selected.relation_id
                JOIN node neighbor
                  ON neighbor.node_id = selected.neighbor_node_id
                ORDER BY
                    selected.p_value,
                    selected.neighbor_node_id,
                    selected.relation_id,
                    selected.member_is_subject,
                    selected.feature_id
                """,
                compact_params,
            ).fetchall()
            selected_rows = _prune_hierarchy_candidate_rows(compact_rows)
            if candidate_window is None or len(compact_rows) < candidate_window:
                break
            if max_results is not None and len(selected_rows) >= max_results:
                cutoff = (
                    selected_rows[max_results - 1][4],
                    selected_rows[max_results - 1][1],
                )
                fetched_boundary = (
                    compact_rows[-1][4],
                    compact_rows[-1][1],
                )
                if fetched_boundary > cutoff:
                    break
            candidate_window *= 4

        if max_results is not None:
            selected_rows = selected_rows[:max_results]
        if not selected_rows:
            return [], total_node_count

        selected_feature_ids = [row[0] for row in selected_rows]
        linked_params = [input_node_ids]
        if hierarchy_exclusion_pairs:
            linked_params.append(
                sorted(
                    {
                        excluded_predicate
                        for excluded_predicate, _ in hierarchy_exclusion_pairs
                    }
                )
            )
        linked_params.append(selected_feature_ids)
        linked_rows = current_connection.execute(
            f"""
            WITH matched_membership AS MATERIALIZED (
                SELECT
                    membership.member_node_id,
                    membership.feature_id
                FROM membership
                WHERE membership.member_node_id IN (SELECT unnest(?))
            )
            {hierarchy_cte}
            ,
            eligible_membership AS (
                SELECT
                    candidate_membership.member_node_id,
                    candidate_membership.feature_id
                FROM matched_membership candidate_membership
                JOIN feature USING (feature_id)
                {hierarchy_join}
                WHERE candidate_membership.feature_id IN (SELECT unnest(?))
                  {hierarchy_filter}
            )
            SELECT
                eligible_membership.feature_id,
                list(member.curie ORDER BY member.curie) AS linked_curies
            FROM eligible_membership
            JOIN node member
              ON member.node_id = eligible_membership.member_node_id
            GROUP BY eligible_membership.feature_id
            """,
            linked_params,
        ).fetchall()
        linked_curies = {
            feature_id: tuple(curies)
            for feature_id, curies in linked_rows
        }
        return [
            EnrichmentCandidate(
                neighbor_curie=row[7],
                predicate_json=row[8],
                member_is_subject=row[3],
                is_symmetric=row[9],
                p_value=row[4],
                support_count=row[5],
                background_count=row[6],
                linked_curies=linked_curies[row[0]],
                neighbor_categories=tuple(row[10]),
            )
            for row in selected_rows
        ], total_node_count

    candidate_limit = ""
    query_params = eligibility_params + scoring_params
    if max_results is not None:
        candidate_limit = "LIMIT ?"
        query_params.append(max_results)
    rows = current_connection.execute(
        f"""
        WITH
        {eligibility_ctes}
        {scoring_ctes}
        ,
        selected AS (
            SELECT
                surviving.feature_id,
                surviving.support_count,
                surviving.background_count,
                surviving.p_value
            FROM surviving
            JOIN feature USING (feature_id)
            {candidate_filter}
            ORDER BY
                surviving.p_value,
                feature.neighbor_node_id,
                feature.relation_id,
                feature.member_is_subject,
                surviving.feature_id
            {candidate_limit}
        ),
        linked AS (
            SELECT
                selected.feature_id,
                selected.support_count,
                selected.background_count,
                selected.p_value,
                list(
                    member.curie
                    ORDER BY member.curie
                ) AS linked_curies
            FROM selected
            JOIN eligible_membership USING (feature_id)
            JOIN node member
              ON member.node_id = eligible_membership.member_node_id
            GROUP BY
                selected.feature_id,
                selected.support_count,
                selected.background_count,
                selected.p_value
        )
        SELECT
            neighbor.curie,
            relation.predicate_json,
            feature.member_is_subject,
            relation.is_symmetric,
            candidate.p_value,
            candidate.support_count,
            candidate.background_count,
            candidate.linked_curies,
            neighbor.categories
        FROM linked candidate
        JOIN feature USING (feature_id)
        JOIN relation USING (relation_id)
        JOIN node neighbor ON neighbor.node_id = feature.neighbor_node_id
        ORDER BY
            candidate.p_value,
            neighbor.curie,
            feature.relation_id,
            feature.member_is_subject
        """,
        query_params,
    ).fetchall()

    return [
        EnrichmentCandidate(
            neighbor_curie=row[0],
            predicate_json=row[1],
            member_is_subject=row[2],
            is_symmetric=row[3],
            p_value=row[4],
            support_count=row[5],
            background_count=row[6],
            linked_curies=tuple(row[7]),
            neighbor_categories=tuple(row[8]),
        )
        for row in rows
    ], total_node_count


def get_edge_provenance(edges):
    edges = list(dict.fromkeys(edges))
    if not edges:
        return {}
    current_connection = connection()
    predicate_jsons = list(dict.fromkeys(edge[1] for edge in edges))
    relations = {
        predicate_json: (relation_id, is_symmetric)
        for predicate_json, relation_id, is_symmetric in current_connection.execute(
            """
            SELECT predicate_json, relation_id, is_symmetric
            FROM relation
            WHERE predicate_json IN (SELECT unnest(?))
            """,
            [predicate_jsons],
        ).fetchall()
    }
    edge_curies = list(
        dict.fromkeys(
            curie
            for subject, _, object_ in edges
            for curie in (subject, object_)
        )
    )
    node_ids = {
        curie: node_id
        for curie, node_id in current_connection.execute(
            """
            SELECT curie, node_id
            FROM node
            WHERE curie IN (SELECT unnest(?))
            """,
            [edge_curies],
        ).fetchall()
    }
    resolved_edges = [
        (
            subject,
            node_ids[subject],
            relations[predicate_json][0],
            object_,
            node_ids[object_],
            relations[predicate_json][1],
        )
        for subject, predicate_json, object_ in edges
        if (
            predicate_json in relations
            and subject in node_ids
            and object_ in node_ids
        )
    ]
    if not resolved_edges:
        return {}

    requested = pyarrow.table(
        {
            "requested_subject": [edge[0] for edge in resolved_edges],
            "subject_node_id": [edge[1] for edge in resolved_edges],
            "relation_id": [edge[2] for edge in resolved_edges],
            "requested_object": [edge[3] for edge in resolved_edges],
            "object_node_id": [edge[4] for edge in resolved_edges],
            "is_symmetric": [edge[5] for edge in resolved_edges],
        }
    )
    current_connection.register("_requested_provenance", requested)
    try:
        rows = current_connection.execute(
            """
            WITH resolved AS (
                SELECT
                    requested.requested_subject,
                    requested.relation_id,
                    requested.requested_object,
                    fact.fact_id
                FROM _requested_provenance requested
                JOIN relation_implication implication
                  ON implication.implied_relation_id
                     = requested.relation_id
                JOIN fact
                  ON fact.relation_id = implication.concrete_relation_id
                 AND fact.subject_node_id = requested.subject_node_id
                 AND fact.object_node_id = requested.object_node_id

                UNION

                SELECT
                    requested.requested_subject,
                    requested.relation_id,
                    requested.requested_object,
                    fact.fact_id
                FROM _requested_provenance requested
                JOIN relation_implication implication
                  ON implication.implied_relation_id
                     = requested.relation_id
                JOIN fact
                  ON requested.is_symmetric
                 AND fact.relation_id = implication.concrete_relation_id
                 AND fact.subject_node_id = requested.object_node_id
                 AND fact.object_node_id = requested.subject_node_id
            )
            SELECT
                resolved.requested_subject,
                resolved.relation_id,
                resolved.requested_object,
                evidence.sources_json
            FROM resolved
            JOIN evidence USING (fact_id)
            ORDER BY evidence.evidence_id
            """
        ).fetchall()
    finally:
        current_connection.unregister("_requested_provenance")

    provenance = {}
    predicate_by_relation = {
        relation_id: predicate_json
        for predicate_json, (relation_id, _) in relations.items()
    }
    for subject, relation_id, object_, sources_json in rows:
        key = (subject, predicate_by_relation[relation_id], object_)
        provenance.setdefault(key, []).append(
            _trapi_sources(orjson.loads(sources_json))
        )
    return provenance
