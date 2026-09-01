from fastapi.testclient import TestClient

from src import server


client = TestClient(server.APP)


def test_ui_is_served_from_root_and_ui_path():
    root_response = client.get("/")
    ui_response = client.get("/ui")
    javascript_response = client.get("/ui/assets/app.js")

    assert root_response.status_code == 200
    assert ui_response.status_code == 200
    assert javascript_response.status_code == 200
    assert "AnswerCoalesce Workbench" in root_response.text
    assert 'data-mode="enrichment"' in root_response.text
    assert 'data-mode="edgar"' in root_response.text
    assert 'data-edgar-stage="matches"' in root_response.text
    assert 'data-edgar-stage="rules"' in root_response.text
    assert 'data-edgar-stage="new"' in root_response.text
    assert "Existing matches" in root_response.text
    assert "Learned rules" in root_response.text
    assert "New entities" in root_response.text
    assert "Relationship qualifiers" in root_response.text
    assert 'id="add-qualifier"' in root_response.text
    assert '"biolink:qualified_predicate"' in javascript_response.text
    assert '"biolink:object_aspect_qualifier"' in javascript_response.text
    assert '"biolink:object_direction_qualifier"' in javascript_response.text
    assert "renderQualifierPills(match.directEdges)" in javascript_response.text
    assert "renderRelationshipQualifiers(edge)" in javascript_response.text


def test_name_resolver_proxy_returns_bounded_fields(monkeypatch):
    async def fake_request(method, url, **kwargs):
        assert method == "GET"
        assert url.endswith("/lookup")
        assert kwargs["params"]["string"] == "asthma"
        return [{
            "curie": "MONDO:0004979",
            "label": "asthma",
            "types": ["biolink:Disease"],
            "taxa": [],
            "score": 12.3,
            "synonyms": ["Asthma"],
        }]

    monkeypatch.setattr(server, "request_identity_service", fake_request)
    response = client.get("/ui-api/resolve", params={"q": "asthma", "limit": 3})

    assert response.status_code == 200
    assert response.json() == {
        "query": "asthma",
        "results": [{
            "curie": "MONDO:0004979",
            "label": "asthma",
            "types": ["biolink:Disease"],
            "taxa": [],
            "score": 12.3,
        }],
    }


def test_biolink_type_metadata_supports_specificity_ranking():
    response = client.get("/ui-api/biolink-types")

    assert response.status_code == 200
    types = response.json()["types"]
    assert types["biolink:Pathway"]["depth"] > types["biolink:BiologicalProcessOrActivity"]["depth"]
    assert types["biolink:BiologicalProcess"]["depth"] > types["biolink:NamedThing"]["depth"]


def test_batch_name_resolver_preserves_requested_terms(monkeypatch):
    async def fake_request(method, url, **kwargs):
        assert method == "POST"
        assert url.endswith("/bulk-lookup")
        assert kwargs["json"]["strings"] == ["PIK3CA", "asthma"]
        return {
            "PIK3CA": [{
                "curie": "NCBIGene:5290",
                "label": "PIK3CA",
                "types": ["biolink:Gene"],
                "taxa": ["NCBITaxon:9606"],
                "score": 100,
            }],
            "asthma": [],
        }

    monkeypatch.setattr(server, "request_identity_service", fake_request)
    response = client.post(
        "/ui-api/resolve-batch",
        json={"terms": [" PIK3CA ", "asthma", "PIK3CA"], "limit": 5},
    )

    assert response.status_code == 200
    assert list(response.json()["results"]) == ["PIK3CA", "asthma"]
    assert response.json()["results"]["PIK3CA"][0]["curie"] == "NCBIGene:5290"
    assert response.json()["results"]["asthma"] == []


def test_node_normalizer_proxy_returns_preferred_identity_and_types(monkeypatch):
    async def fake_request(method, url, **kwargs):
        assert method == "POST"
        assert url.endswith("/get_normalized_nodes")
        assert kwargs["json"]["curies"] == ["NCBIGene:5290", "UNKNOWN:1"]
        return {
            "NCBIGene:5290": {
                "id": {"identifier": "NCBIGene:5290", "label": "PIK3CA"},
                "equivalent_identifiers": [
                    {"identifier": "NCBIGene:5290"},
                    {"identifier": "HGNC:8975"},
                ],
                "type": ["biolink:Gene", "biolink:GeneOrGeneProduct"],
                "taxa": ["NCBITaxon:9606"],
                "information_content": 78.0,
            },
            "UNKNOWN:1": None,
        }

    monkeypatch.setattr(server, "request_identity_service", fake_request)
    response = client.post(
        "/ui-api/normalize",
        json={"curies": ["NCBIGene:5290", "UNKNOWN:1"]},
    )

    assert response.status_code == 200
    entities = response.json()["entities"]
    assert entities[0]["curie"] == "NCBIGene:5290"
    assert entities[0]["label"] == "PIK3CA"
    assert entities[0]["types"] == ["biolink:Gene", "biolink:GeneOrGeneProduct"]
    assert entities[0]["equivalent_identifier_count"] == 2
    assert entities[0]["normalized"] is True
    assert entities[1]["curie"] == "UNKNOWN:1"
    assert entities[1]["normalized"] is False
