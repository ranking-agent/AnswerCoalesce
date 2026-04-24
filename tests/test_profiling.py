import cProfile
import pstats
import sys
import json
from fastapi.testclient import TestClient

from src.server import APP
from tests.conftest import generate_infer_query, generate_mcq_query

client = TestClient(APP)


def profile_request(label, in_message):
    print(f'\n== Profiling {label} ==')
    print(f'Query: {json.dumps(in_message["message"]["query_graph"]["edges"], indent=2)}')

    with cProfile.Profile() as profile:
        response = client.post('/query', json=in_message)

    if response.status_code != 200:
        print(f'ERROR: status {response.status_code}')
        print(response.text[:500])
        return

    jret = json.loads(response.content)
    message = jret.get('message', {})

    stats = pstats.Stats(profile)
    stats.strip_dirs().sort_stats("cumulative")
    stats.print_stats(30)

    results = message.get('results', [])
    aux = message.get('auxiliary_graphs', {})
    kg_nodes = len(message.get('knowledge_graph', {}).get('nodes', {}))
    kg_edges = len(message.get('knowledge_graph', {}).get('edges', {}))

    print(f'{"=" * 50}')
    print(f'  Results: {len(results)}')
    print(f'  KG nodes: {kg_nodes}, KG edges: {kg_edges}')
    if aux:
        if label == "infer":
            count_n_ac = sum(1 for key in aux if '_n_Inferred_SG' in key)
            count_e_ac = sum(1 for key in aux if 'e_Inferred_SG' in key)
            print(f'  Property coalesce (_n_ac): {count_n_ac}')
            print(f'  Graph coalesce (_e_ac): {count_e_ac}')
        else:
            count_support = sum(1 for key in aux if 'SG:_' in key)
            print(f'  Support Graphs (SG:_): {count_support}')
    print(f'{"=" * 50}')


def profile_infer(curie, predicate, input_type, output_type, is_subject):
    in_message = generate_infer_query(
        input_type, output_type, curie, predicate,
        input_is_subject=is_subject,
        params={"pvalue_threshold": 1e-05, "max_rules": 100}
    )
    profile_request(f'infer: {curie} -> {output_type}', in_message)


def profile_mcq(member_ids, predicate, input_type, output_type, is_subject):
    in_message = generate_mcq_query(
        input_type, output_type, member_ids, predicate,
        input_is_subject=is_subject
    )
    profile_request(f'mcq: {len(member_ids)} {input_type} -> {output_type}', in_message)


USAGE = """Usage:
  python tests/test_profiling.py infer <curie> <predicate> <input_type> <output_type> [--object]
  python tests/test_profiling.py mcq <member_ids_csv> <predicate> <input_type> <output_type> [--object]

Examples:
  python tests/test_profiling.py infer MONDO:0004975 biolink:treats biolink:Disease biolink:Drug --object
  python tests/test_profiling.py mcq NCBIGene:5111,NCBIGene:8856,NCBIGene:5290 biolink:related_to biolink:Gene biolink:ChemicalEntity

Flags:
  --object   Input curie/members are the object (default: subject)
"""

if __name__ == '__main__':
    if len(sys.argv) < 6:
        print(USAGE)
        sys.exit(1)

    mode = sys.argv[1]
    is_subject = '--object' not in sys.argv
    args = [a for a in sys.argv[2:] if a != '--object']

    if mode == 'infer':
        curie, predicate, input_type, output_type = args[0], args[1], args[2], args[3]
        profile_infer(curie, predicate, input_type, output_type, is_subject)
    elif mode == 'mcq':
        member_ids = args[0].split(',')
        predicate, input_type, output_type = args[1], args[2], args[3]
        profile_mcq(member_ids, predicate, input_type, output_type, is_subject)
    else:
        print(f'Unknown mode: {mode}')
        print(USAGE)
        sys.exit(1)