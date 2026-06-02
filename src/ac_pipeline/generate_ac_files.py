import argparse
from src.graph_coalescence.build_redis_files import generate_ac_files, generate_ac_redis


def main():
    ap = argparse.ArgumentParser(
        description='Generate AnswerCoalesce data from KGX node/edge JSONL files.'
    )
    ap.add_argument('-n', '--nodes', help='Input node file path (JSONL)', required=True)
    ap.add_argument('-e', '--edges', help='Input edge file path (JSONL)', required=True)

    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument('-o', '--outdir', help='Output directory for txt files (legacy mode)')
    mode.add_argument('--redis', action='store_true', help='Write directly to Redis (skip txt files)')

    ap.add_argument('--redis-host', default='localhost', help='Redis host (default: localhost)')
    ap.add_argument('--redis-port', default=6379, type=int, help='Redis port (default: 6379)')

    args = ap.parse_args()

    if args.redis:
        generate_ac_redis(
            input_node_file=args.nodes,
            input_edge_file=args.edges,
            redis_host=args.redis_host,
            redis_port=args.redis_port,
        )
    else:
        generate_ac_files(
            input_node_file=args.nodes,
            input_edge_file=args.edges,
            output_dir=args.outdir,
        )


if __name__ == '__main__':
    main()
