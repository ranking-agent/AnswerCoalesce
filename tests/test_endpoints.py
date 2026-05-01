import pytest, json
from fastapi.testclient import TestClient
from reasoner_pydantic import Response as PDResponse

from src.server import APP
from tests.conftest import generate_infer_query, generate_mcq_query

client = TestClient(APP)

EXCLUDE_PREDICATES = [
    "biolink:causes", "biolink:biomarker_for", "biolink:contraindicated_for",
    "biolink:contributes_to", "biolink:has_adverse_event", "biolink:causes_adverse_event"
]


def run_test(in_message):
    assert PDResponse.parse_obj(in_message)
    response = client.post('/query', json=in_message)
    assert response.status_code == 200
    return json.loads(response.content)


def confirm_qg_nodes(in_message, jret, is_source_ids=False):
    message = jret['message']
    kgnodes = message["knowledge_graph"]["nodes"]
    kgedges = message["knowledge_graph"]["edges"]
    result0 = message['results'][0]
    assert len(result0['node_bindings']) == 2

    if is_source_ids:
        input_ids_from = "subject"
        output_cat_from = "object"
    else:
        input_ids_from = "object"
        output_cat_from = "subject"

    query_graph = in_message['message']['query_graph']
    for qgedge_id, qgedge in query_graph['edges'].items():
        inferred_edges = result0["analyses"][0]["edge_bindings"][qgedge_id][0]["id"]
        the_edge = kgedges[inferred_edges]
        assert query_graph['nodes'][qgedge[input_ids_from]]['ids'][0] == the_edge[input_ids_from]
        assert query_graph['nodes'][qgedge[output_cat_from]]['categories'][0] in \
               kgnodes[the_edge[output_cat_from]]['categories']


@pytest.mark.nongithub
def test_drugs_to_disease_inference():
    in_message = generate_infer_query(
        "biolink:Disease", "biolink:Drug", "MONDO:0004975", "biolink:treats",
        input_is_subject=False,
        params={
            "pvalue_threshold": 1e-05, "max_rules": 100,
            "predicate_constraint_style": "exclude",
            "predicate_constraints": EXCLUDE_PREDICATES
        }
    )
    jret = run_test(in_message)
    assert len(jret["message"]) == 4


@pytest.mark.nongithub
def test_genes_to_disease_inference():
    in_message = generate_infer_query(
        "biolink:Disease", "biolink:Gene", "MONDO:0004979", "biolink:genetically_associated_with",
        input_is_subject=False,
        params={"pvalue_threshold": 1e-05, "max_rules": 100, "predicate_constraint_style": "exclude",
                "predicate_constraints": EXCLUDE_PREDICATES}
    )
    jret = run_test(in_message)
    with open("NYESQC.json", "w") as outfile:
        json.dump(jret, outfile)
    assert len(jret["message"]) == 4
    confirm_qg_nodes(in_message, jret, is_source_ids=False)


@pytest.mark.nongithub
def test_disease_to_phenotypes_inference():
    in_message = generate_infer_query(
        "biolink:Disease", "biolink:PhenotypicFeature", "MONDO:0005147", "biolink:has_phenotype",
        input_is_subject=True,
        params={"pvalue_threshold": 1e-05, "max_results": 100, "predicate_constraints": []}
    )
    jret = run_test(in_message)
    assert len(jret["message"]) == 4
    confirm_qg_nodes(in_message, jret, is_source_ids=True)


HUMAN_SPECIES_QUALIFIER = [{"qualifier_set": [
    {"qualifier_type_id": "biolink:species_context_qualifier",
     "qualifier_value": "NCBITaxon:9606"}
]}]


@pytest.mark.nongithub
def test_context_qualifier_changes_results():
    """Verify species_context_qualifier actually filters enrichment results.
    Same query with vs. without human context should produce different result sets."""
    base_params = {
        "pvalue_threshold": 1e-05, "max_rules": 100,
        "predicate_constraint_style": "exclude",
        "predicate_constraints": EXCLUDE_PREDICATES
    }

    # Without context
    msg_no_ctx = generate_infer_query(
        "biolink:Disease", "biolink:Drug", "MONDO:0004975", "biolink:treats",
        input_is_subject=False, params=base_params
    )
    ret_no_ctx = run_test(msg_no_ctx)

    # With human species context
    msg_human = generate_infer_query(
        "biolink:Disease", "biolink:Drug", "MONDO:0004975", "biolink:treats",
        input_is_subject=False, params=base_params,
        qualifier_constraints=HUMAN_SPECIES_QUALIFIER
    )
    ret_human = run_test(msg_human)

    results_no_ctx = ret_no_ctx["message"].get("results", [])
    results_human = ret_human["message"].get("results", [])

    # Both should produce results
    assert len(results_no_ctx) > 0, "No-context query returned no results"
    assert len(results_human) > 0, "Human-context query returned no results"

    # The result counts should differ — context filtering narrows enrichment
    ids_no_ctx = {r["node_bindings"]["output"][0]["id"] for r in results_no_ctx}
    ids_human = {r["node_bindings"]["output"][0]["id"] for r in results_human}
    assert ids_no_ctx != ids_human, (
        "Context qualifier had no effect on results — filtering may not be working"
    )

    # Human-filtered should be a subset (or at least smaller)
    # since context restricts which links enter enrichment
    assert len(ids_human) <= len(ids_no_ctx), (
        f"Human-context ({len(ids_human)}) returned more results than no-context ({len(ids_no_ctx)})"
    )


@pytest.mark.nongithub
def test_context_qualifiers_preserved_on_edges():
    """Verify that species_context_qualifier appears on support edges in the output.
    When querying with human context, edges that came from human-specific links
    should carry the species_context_qualifier in their qualifiers list."""
    in_message = generate_infer_query(
        "biolink:Disease", "biolink:Gene", "MONDO:0004979", "biolink:genetically_associated_with",
        input_is_subject=False,
        params={
            "pvalue_threshold": 1e-05, "max_rules": 100,
            "predicate_constraint_style": "exclude",
            "predicate_constraints": EXCLUDE_PREDICATES
        },
        qualifier_constraints=HUMAN_SPECIES_QUALIFIER
    )
    jret = run_test(in_message)
    kg_edges = jret["message"]["knowledge_graph"]["edges"]

    # Check if any edge in the KG carries a species_context_qualifier
    edges_with_species_ctx = []
    for eid, edge in kg_edges.items():
        for q in edge.get("qualifiers", []):
            if q.get("qualifier_type_id") == "biolink:species_context_qualifier":
                edges_with_species_ctx.append(eid)
                break

    assert len(edges_with_species_ctx) > 0, (
        "No edges in the output carry species_context_qualifier — "
        "context qualifiers are being stripped from support edges"
    )


@pytest.mark.nongithub
def test_genes_to_chemical_mcq():
    in_message = generate_mcq_query(
        "biolink:Gene", "biolink:ChemicalEntity",
        ["NCBIGene:5297", "NCBIGene:5298", "NCBIGene:5290"],
        "biolink:related_to", input_is_subject=True
    )
    jret = run_test(in_message)
    assert len(jret["message"]) == 4
    confirm_qg_nodes(in_message, jret, is_source_ids=True)


@pytest.mark.nongithub
def test_mcq_with_qualifier_constraints():
    """MCQ query with species_context_qualifier should produce results
    and carry qualifiers through to the output edges."""
    in_message = generate_mcq_query(
        "biolink:Gene", "biolink:Gene",
        ["NCBIGene:10469", "NCBIGene:2932", "NCBIGene:1500"],
        "biolink:interacts_with", input_is_subject=True,
        qualifier_constraints=HUMAN_SPECIES_QUALIFIER
    )
    jret = run_test(in_message)
    message = jret["message"]
    assert "results" in message
    assert len(message["results"]) >= 1, "MCQ with species qualifier returned no results"

    # Verify qualifier appears on result edges
    kg_edges = message["knowledge_graph"]["edges"]
    edges_with_species = [
        eid for eid, edge in kg_edges.items()
        for q in edge.get("qualifiers", [])
        if q.get("qualifier_type_id") == "biolink:species_context_qualifier"
    ]
    assert len(edges_with_species) > 0, (
        "MCQ output edges missing species_context_qualifier"
    )


@pytest.mark.nongithub
def test_multicurieac():
    in_message = generate_mcq_query(
        "biolink:Gene", "biolink:ChemicalEntity",
        ["NCBIGene:5111", "NCBIGene:8856", "NCBIGene:5290"],
        "biolink:related_to", input_is_subject=True
    )
    assert PDResponse.parse_obj(in_message)
    jret = run_test(in_message)
    message = jret['message']
    assert 'results' in message
    assert len(message['results']) >= 1


@pytest.mark.nongithub
def test_phenotype_to_gene_mcq_no_enrichment():
    in_message = generate_mcq_query(
        "biolink:PhenotypicFeature", "biolink:Gene",
        ["HP:0000729", "HP:0012758", "HP:0001249", "HP:0001629", "HP:0001999",
         "HP:0002705", "HP:0000426", "HP:0000586", "HP:0010490"],
        "biolink:genetically_associated_with", input_is_subject=True
    )
    jret = run_test(in_message)
    assert len(jret["message"]) == 2