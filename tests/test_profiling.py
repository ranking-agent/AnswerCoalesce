import asyncio
import cProfile
import pstats
import sys
import json

from src.single_node_coalescer import infer, multi_curie_query
from src.server import get_parameters
from tests.conftest import generate_infer_query, generate_mcq_query


def profile_pipeline(label, coro):
    print(f'\n== Profiling {label} ==')

    with cProfile.Profile() as profile:
        result = asyncio.run(coro)

    message = result.get('message', {})

    stats = pstats.Stats(profile)
    stats.strip_dirs().sort_stats("cumulative")
    stats.print_stats(40)

    results = message.get('results', [])
    aux = message.get('auxiliary_graphs', {})
    kg_nodes = len(message.get('knowledge_graph', {}).get('nodes', {}))
    kg_edges = len(message.get('knowledge_graph', {}).get('edges', {}))

    print(f'{"=" * 50}')
    print(f'  Results: {len(results)}')
    print(f'  KG nodes: {kg_nodes}, KG edges: {kg_edges}')
    if aux:
        count_graph = sum(1 for key in aux if 'e_Inferred_SG' in key)
        count_prop = sum(1 for key in aux if 'n_Inferred_SG' in key)
        count_mcq = sum(1 for key in aux if key.startswith('SG:_'))
        if count_graph or count_prop:
            print(f'  Graph coalesce Inference (e_Inferred_SG): {count_graph}')
            print(f'  Property coalesce Inference (n_Inferred_SG): {count_prop}')
        if count_mcq:
            print(f'  Enrichment support graphs (SG:_): {count_mcq}')
    print(f'{"=" * 50}')


async def run_infer(in_message):
    return await infer(in_message)


async def run_mcq(in_message):
    parameters = await get_parameters(in_message)
    return await multi_curie_query(in_message, parameters)


def profile_infer(curie, predicate, input_type, output_type, is_subject):
    in_message = generate_infer_query(
        input_type, output_type, curie, predicate,
        input_is_subject=is_subject,
        params={"pvalue_threshold": 1e-05, "max_rules": 100}
    )
    print(f'Query edge: {json.dumps(in_message["message"]["query_graph"]["edges"], indent=2)}')
    profile_pipeline(f'infer: {curie} -> {output_type}', run_infer(in_message))


def profile_mcq(member_ids, predicate, input_type, output_type, is_subject):
    in_message = generate_mcq_query(
        input_type, output_type, member_ids, predicate,
        input_is_subject=is_subject
    )
    print(f'Query edge: {json.dumps(in_message["message"]["query_graph"]["edges"], indent=2)}')
    profile_pipeline(f'mcq: {len(member_ids)} {input_type} -> {output_type}', run_mcq(in_message))


USAGE = """Usage:
  PYTHONPATH=. python tests/test_profiling.py infer <curie> <predicate> <input_type> <output_type> [--object]
  PYTHONPATH=. python tests/test_profiling.py mcq <member_ids_csv> <predicate> <input_type> <output_type> [--object]

Examples:
  PYTHONPATH=. python tests/test_profiling.py infer MONDO:0004975 biolink:treats biolink:Disease biolink:Drug --object
  PYTHONPATH=. python tests/test_profiling.py mcq NCBIGene:5111,NCBIGene:8856,NCBIGene:5290 biolink:related_to biolink:Gene biolink:ChemicalEntity

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