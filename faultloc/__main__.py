"""Command-line entry point."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from faultloc.harvest import (
    DEFAULT_MAX_MUTANTS,
    DEFAULT_MAX_PER_FUNCTION,
    DEFAULT_SEED,
    DEFAULT_TIMEOUT_SECONDS,
    harvest,
)
from faultloc.eval import evaluate


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m faultloc")
    subparsers = parser.add_subparsers(dest="command")
    harvest_parser = subparsers.add_parser("harvest", help="generate benchmark cases")
    harvest_parser.add_argument("--max-mutants", type=int, default=DEFAULT_MAX_MUTANTS)
    harvest_parser.add_argument(
        "--max-per-function", type=int, default=DEFAULT_MAX_PER_FUNCTION
    )
    harvest_parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    harvest_parser.add_argument(
        "--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS
    )
    eval_parser = subparsers.add_parser("eval", help="evaluate fault localizers")
    eval_parser.add_argument(
        "--dense", action="store_true", help="try the optional ONNX dense baseline"
    )
    eval_parser.add_argument(
        "--experiments",
        action="store_true",
        help="include reverted Phase 4 attempts in the dev evaluation",
    )
    eval_parser.add_argument(
        "--final-test",
        action="store_true",
        help="run the locked test split once and archive the dev results",
    )
    serve_parser = subparsers.add_parser("serve", help="serve the cached dashboard")
    serve_parser.add_argument("--host", default="0.0.0.0")
    serve_parser.add_argument(
        "--port", type=int, default=int(os.environ.get("PORT", "8000"))
    )
    arguments = parser.parse_args()
    if arguments.command == "harvest":
        harvest(
            root=Path.cwd(),
            max_mutants=arguments.max_mutants,
            max_per_function=arguments.max_per_function,
            seed=arguments.seed,
            timeout_seconds=arguments.timeout,
        )
    elif arguments.command == "eval":
        if arguments.final_test and (arguments.dense or arguments.experiments):
            parser.error("--final-test cannot be combined with --dense or --experiments")
        evaluate(
            root=Path.cwd(),
            split="test" if arguments.final_test else "dev",
            include_dense=arguments.dense,
            include_experiments=arguments.experiments,
            final_test=arguments.final_test,
        )
    elif arguments.command == "serve":
        import uvicorn

        from faultloc.app import create_app

        uvicorn.run(create_app(Path.cwd()), host=arguments.host, port=arguments.port)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
