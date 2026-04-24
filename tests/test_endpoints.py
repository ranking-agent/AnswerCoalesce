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
def test_drugs_to_disease_inference_human_context():
    in_message = generate_infer_query(
        "biolink:Disease", "biolink:Drug", "MONDO:0004975", "biolink:treats",
        input_is_subject=False,
        params={
            "pvalue_threshold": 1e-05, "max_rules": 100,
            "predicate_constraint_style": "exclude",
            "predicate_constraints": EXCLUDE_PREDICATES
        },
        qualifier_constraints=HUMAN_SPECIES_QUALIFIER
    )
    jret = run_test(in_message)
    assert len(jret["message"]) == 4
    confirm_qg_nodes(in_message, jret, is_source_ids=False)


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