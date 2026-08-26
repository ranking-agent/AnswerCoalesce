import pytest
from src.graph_coalescence.build_redis_files import extract_prov, generate_ac_files
from src.graph_coalescence.graph_coalescer import process_prov
import os, json, jsonlines, bmt

def test_redis_build():
    testdir = os.path.join(os.path.abspath(os.path.dirname(__file__)), "RedisParseTestData")
    edgefile = os.path.join(testdir, 'edges.jsonl')
    nodefile = os.path.join(testdir, 'nodes.jsonl')
    outdir = os.path.join(testdir, 'output')
    os.makedirs(outdir, exist_ok=True)
    generate_ac_files(input_node_file=nodefile,
       input_edge_file=edgefile,
       output_dir=outdir)

    linkfile = os.path.join(outdir, 'links.txt')
    with open(linkfile, 'r') as inf:
        linkfile_content = [line for line in inf]
    tk = bmt.Toolkit()
    assertion = []

    with jsonlines.open(edgefile, 'r') as inf:
        for line in inf:
            predicate_parts = {'predicate': line['predicate']}
            for key, value in line.items():
                if tk.is_qualifier(key):
                    predicate_parts[key] = value
            predicate_string = json.dumps(predicate_parts, sort_keys=True)
            assert f'{line["subject"]}\t{json.dumps([(line["object"], predicate_string, True)])}\n' in linkfile_content
            if f'{line["subject"]}\t{json.dumps([(line["object"], predicate_string, True)])}\n' not in assertion:
                assertion.append(f'{line["subject"]}\t{json.dumps([(line["object"], predicate_string, True)])}\n')
            is_target = tk.is_symmetric(line['predicate'])
            assert f'{line["object"]}\t{json.dumps([(line["subject"], predicate_string, is_target)])}\n' in linkfile_content
            if f'{line["object"]}\t{json.dumps([(line["subject"], predicate_string, is_target)])}\n' not in assertion:
                assertion.append(f'{line["object"]}\t{json.dumps([(line["subject"], predicate_string, is_target)])}\n')
        assert assertion == linkfile_content

    provfile = os.path.join(outdir, 'prov.txt')
    with open(provfile, 'r') as prov_input:
        _, provenance = prov_input.read().split('\t', 1)
    assert json.loads(provenance) == {
        "biolink:primary_knowledge_source": "infores:string"
    }


def test_robokop_provenance_is_preserved():
    edge = {
        "biolink:primary_knowledge_source": "infores:primary",
        "biolink:aggregator_knowledge_source": ["infores:aggregator"],
    }

    provenance = extract_prov(edge)

    assert provenance == edge
    assert process_prov(json.dumps(provenance)) == [
        {
            "resource_id": "infores:primary",
            "resource_role": "primary_knowledge_source",
        },
        {
            "resource_id": "infores:aggregator",
            "resource_role": "aggregator_knowledge_source",
        },
    ]


def test_translator_provenance_is_preserved():
    sources = [
        {
            "id": "infores:primary",
            "category": ["biolink:RetrievalSource"],
            "resource_id": "infores:primary",
            "resource_role": "primary_knowledge_source",
            "source_record_urls": ["https://example.org/record/1"],
        },
        {
            "id": "infores:supporting",
            "category": ["biolink:RetrievalSource"],
            "resource_id": "infores:supporting",
            "resource_role": "supporting_data_source",
            "upstream_resource_ids": ["infores:primary"],
        },
    ]
    edge = {
        "id": "edge-1",
        "subject": "SUBJECT:1",
        "predicate": "biolink:related_to",
        "object": "OBJECT:1",
        "sources": sources,
    }

    provenance = extract_prov(edge)

    assert provenance == sources
    assert process_prov(json.dumps(provenance).encode()) == sources


@pytest.mark.parametrize(
    "sources",
    [
        [],
        [
            {
                "resource_id": "infores:aggregator",
                "resource_role": "aggregator_knowledge_source",
            }
        ],
        [
            {
                "resource_id": "infores:primary-1",
                "resource_role": "primary_knowledge_source",
            },
            {
                "resource_id": "infores:primary-2",
                "resource_role": "primary_knowledge_source",
            },
        ],
    ],
)
def test_translator_provenance_requires_exactly_one_primary_source(sources):
    edge = {
        "id": "invalid-edge",
        "subject": "SUBJECT:1",
        "predicate": "biolink:related_to",
        "object": "OBJECT:1",
        "sources": sources,
    }

    with pytest.raises(
        ValueError,
        match="must have exactly one primary_knowledge_source",
    ):
        extract_prov(edge)


def test_robokop_provenance_requires_exactly_one_primary_source():
    edge = {
        "id": "invalid-edge",
        "primary_knowledge_source": ["infores:primary-1", "infores:primary-2"],
    }

    with pytest.raises(
        ValueError,
        match="must have exactly one primary_knowledge_source",
    ):
        extract_prov(edge)


def test_translator_primary_source_requires_resource_id():
    edge = {
        "id": "invalid-edge",
        "sources": [
            {
                "resource_role": "primary_knowledge_source",
            }
        ],
    }

    with pytest.raises(
        ValueError,
        match="primary_knowledge_source without a resource_id",
    ):
        extract_prov(edge)
