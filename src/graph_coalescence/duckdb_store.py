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


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_QUERY_MEMORY_LIMIT = "4GB"
DEFAULT_QUERY_MAX_TEMP_DIRECTORY_SIZE = "8GB"
DEFAULT_QUERY_THREADS = 2
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
        with _udf_lock:
            udf_exists = cached_connection.execute(
                """
                SELECT count(*)
                FROM duckdb_functions()
                WHERE function_name = 'ac_poisson_survival'
                """
            ).fetchone()[0]
            if not udf_exists:
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
            "temp_directory": os.getenv(
                "AC_DUCKDB_QUERY_TEMP_DIRECTORY",
                f"/tmp/answer-coalesce-duckdb-{os.getpid()}",
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
    return cached_connection


def close_connection():
    cached_connection = getattr(_thread_state, "connection", None)
    if cached_connection is not None:
        cached_connection.close()
    _thread_state.connection = None
    _thread_state.path = None


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
    rows = connection().execute(
        "SELECT relation_id, predicate_json FROM relation"
    ).fetchall()
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


def create_nodes_to_links(allnodes, param_predicates=None):
    unique_nodes = list(dict.fromkeys(allnodes))
    result = {node: [] for node in unique_nodes}
    if not unique_nodes:
        return result

    rows = connection().execute(
        """
        SELECT
            membership.member_curie,
            membership.neighbor_curie,
            relation.predicate_json,
            membership.member_is_subject
        FROM membership
        JOIN relation USING (relation_id)
        WHERE membership.member_curie IN (SELECT unnest(?))
        """,
        [unique_nodes],
    ).fetchall()

    predicates_by_node = {}
    if param_predicates:
        for node, predicate in zip(allnodes, param_predicates):
            predicates_by_node.setdefault(node, []).append(_normalized_constraint(predicate))

    for member, neighbor, relation_json, member_is_subject in rows:
        constraints = predicates_by_node.get(member)
        if constraints:
            relation = orjson.loads(relation_json)
            if not any(constraint.items() <= relation.items() for constraint in constraints):
                continue
        result[member].append([neighbor, relation_json, member_is_subject])
    return result


def enrichment_candidates(
    input_ids,
    input_category,
    *,
    node_constraints=None,
    predicate_constraints=None,
    predicate_constraint_style="exclude",
    context_qualifiers=None,
    hierarchy_exclusion_pairs=None,
    pvalue_threshold=None,
    max_results=None,
):
    input_ids = list(dict.fromkeys(input_ids))
    if not input_ids:
        return [], 0

    total_counts = get_total_node_counts(input_category)
    total_node_count = int(total_counts.get(input_category, 0))
    if total_node_count == 0:
        return [], 0
    background_category = (
        input_category
        if connection().execute(
            "SELECT count(*) FROM category_count WHERE category = ?",
            [input_category],
        ).fetchone()[0]
        else "biolink:NamedThing"
    )

    relation_ids = sorted(
        _relation_ids(
            predicate_constraints,
            predicate_constraint_style,
            context_qualifiers,
        )
    )
    if not relation_ids:
        return [], total_node_count

    hierarchy_exclusion_pairs = hierarchy_exclusion_pairs or []
    hierarchy_cte = ""
    hierarchy_filter = ""
    query_params = [input_ids]
    if hierarchy_exclusion_pairs:
        hierarchy_cte = """,
        hierarchy_pairs AS (
            SELECT
                unnest(?) AS excluded_predicate,
                unnest(?) AS ancestor_predicate
        )
        """
        query_params.extend(
            [
                [pair[0] for pair in hierarchy_exclusion_pairs],
                [pair[1] for pair in hierarchy_exclusion_pairs],
            ]
        )
        hierarchy_filter = """
          AND NOT EXISTS (
              SELECT 1
              FROM membership excluded_membership
              JOIN relation excluded_relation USING (relation_id)
              JOIN hierarchy_pairs
                ON hierarchy_pairs.excluded_predicate = excluded_relation.predicate
               AND hierarchy_pairs.ancestor_predicate = relation.predicate
              WHERE excluded_membership.member_curie = membership.member_curie
                AND excluded_membership.neighbor_curie = membership.neighbor_curie
                AND excluded_membership.member_is_subject = membership.member_is_subject
          )
        """

    query_params.append(relation_ids)
    query_params.extend(BLOCKLIST)
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

    candidate_limit = ""
    if max_results is not None:
        candidate_limit = "LIMIT ?"

    query_params.extend(
        [
            len(input_ids),
            total_node_count,
            background_category,
            len(input_ids),
            total_node_count,
        ]
    )
    if pvalue_threshold is not None:
        query_params.append(pvalue_threshold)
    if max_results is not None:
        query_params.append(max_results)
    rows = connection().execute(
        f"""
        WITH input AS (
            SELECT DISTINCT unnest(?) AS member_curie
        )
        {hierarchy_cte}
        ,
        candidate_support AS (
            SELECT
                membership.neighbor_curie,
                membership.relation_id,
                membership.member_is_subject,
                count(*)::BIGINT AS support_count
            FROM input
            JOIN membership USING (member_curie)
            JOIN relation USING (relation_id)
            JOIN node neighbor ON neighbor.curie = membership.neighbor_curie
            WHERE membership.relation_id IN (SELECT unnest(?))
              AND membership.neighbor_curie NOT IN (
                  {",".join("?" for _ in BLOCKLIST)}
              )
              {hierarchy_filter}
              {category_filter}
            GROUP BY
                membership.neighbor_curie,
                membership.relation_id,
                membership.member_is_subject
        ),
        surviving AS (
            SELECT
                candidate.neighbor_curie,
                candidate.relation_id,
                candidate.member_is_subject,
                candidate.support_count,
                stats.background_count,
                ac_poisson_survival(
                    candidate.support_count,
                    stats.background_count * ?::DOUBLE / ?
                ) AS p_value
            FROM candidate_support candidate
            JOIN feature_stats stats
              ON stats.category = ?
             AND stats.neighbor_curie = candidate.neighbor_curie
             AND stats.relation_id = candidate.relation_id
             AND stats.member_is_subject = candidate.member_is_subject
            WHERE candidate.support_count >= stats.background_count * ? / ?
        ),
        selected AS (
            SELECT *
            FROM surviving
            {candidate_filter}
            ORDER BY
                p_value,
                neighbor_curie,
                relation_id,
                member_is_subject
            {candidate_limit}
        ),
        linked AS (
            SELECT
                selected.neighbor_curie,
                selected.relation_id,
                selected.member_is_subject,
                selected.support_count,
                selected.background_count,
                selected.p_value,
                list(
                    membership.member_curie
                    ORDER BY membership.member_curie
                ) AS linked_curies
            FROM selected
            JOIN input ON TRUE
            JOIN membership
              ON membership.member_curie = input.member_curie
             AND membership.neighbor_curie = selected.neighbor_curie
             AND membership.relation_id = selected.relation_id
             AND membership.member_is_subject = selected.member_is_subject
            GROUP BY
                selected.neighbor_curie,
                selected.relation_id,
                selected.member_is_subject,
                selected.support_count,
                selected.background_count,
                selected.p_value
        )
        SELECT
            candidate.neighbor_curie,
            relation.predicate_json,
            candidate.member_is_subject,
            relation.is_symmetric,
            candidate.p_value,
            candidate.support_count,
            candidate.background_count,
            candidate.linked_curies,
            neighbor.categories
        FROM linked candidate
        JOIN relation USING (relation_id)
        JOIN node neighbor ON neighbor.curie = candidate.neighbor_curie
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
    resolved_edges = [
        (
            subject,
            relations[predicate_json][0],
            object_,
            relations[predicate_json][1],
        )
        for subject, predicate_json, object_ in edges
        if predicate_json in relations
    ]
    if not resolved_edges:
        return {}

    requested = pyarrow.table(
        {
            "requested_subject": [edge[0] for edge in resolved_edges],
            "relation_id": [edge[1] for edge in resolved_edges],
            "requested_object": [edge[2] for edge in resolved_edges],
            "is_symmetric": [edge[3] for edge in resolved_edges],
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
                JOIN fact
                  ON fact.relation_id = requested.relation_id
                 AND fact.subject_curie = requested.requested_subject
                 AND fact.object_curie = requested.requested_object

                UNION

                SELECT
                    requested.requested_subject,
                    requested.relation_id,
                    requested.requested_object,
                    fact.fact_id
                FROM _requested_provenance requested
                JOIN fact
                  ON requested.is_symmetric
                 AND fact.relation_id = requested.relation_id
                 AND fact.subject_curie = requested.requested_object
                 AND fact.object_curie = requested.requested_subject
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
