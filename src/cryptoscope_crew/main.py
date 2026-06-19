#!/usr/bin/env python
"""CLI d'entrée du crew CryptoScope.

Tous les flags sont optionnels : les valeurs absentes sont résolues par
`inject_runtime_inputs` (variables d'env PAIRS, TIMEFRAME, LOOKBACK, ...).
"""
import argparse
import sys
import warnings

from cryptoscope_crew.crew import CryptoscopeCrew

warnings.filterwarnings("ignore", category=SyntaxWarning, module="pysbd")


def _parse_kv_inputs(items: list[str] | None) -> dict:
    """Parse les paires KEY=VALUE de --inputs."""
    out = {}
    for item in items or []:
        if "=" not in item:
            raise SystemExit(f"--inputs attend KEY=VALUE, reçu: {item!r}")
        k, v = item.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def build_inputs(argv: list[str] | None = None) -> dict:
    parser = argparse.ArgumentParser(
        prog="cryptoscope",
        description="Lance le crew CryptoScope (scan marché + TA + rapport).",
    )
    parser.add_argument("--pairs", help="Paires séparées par des virgules, ex: BTC/USDC,ETH/USDC")
    parser.add_argument("--timeframe", help="Timeframe principal, ex: 1d")
    parser.add_argument("--lookback", type=int, help="Nombre de chandeliers d'historique")
    parser.add_argument("--tz", help="Fuseau horaire, ex: Europe/Paris")
    parser.add_argument("--output-dir", dest="output_dir", help="Dossier des rapports")
    parser.add_argument(
        "--inputs", nargs="*", metavar="KEY=VALUE", default=None,
        help="Inputs additionnels passés tels quels au crew",
    )
    args = parser.parse_args(argv)

    inputs = _parse_kv_inputs(args.inputs)
    for key in ("pairs", "timeframe", "lookback", "tz", "output_dir"):
        val = getattr(args, key)
        if val is not None:
            inputs[key] = val
    return inputs


def run(argv: list[str] | None = None):
    """
    Run the crew.
    """
    inputs = build_inputs(argv)
    CryptoscopeCrew().crew().kickoff(inputs=inputs)


def train():
    """
    Train the crew for a given number of iterations.
    """
    try:
        CryptoscopeCrew().crew().train(n_iterations=int(sys.argv[1]), filename=sys.argv[2], inputs={})
    except Exception as e:
        raise Exception(f"An error occurred while training the crew: {e}")


def replay():
    """
    Replay the crew execution from a specific task.
    """
    try:
        CryptoscopeCrew().crew().replay(task_id=sys.argv[1])
    except Exception as e:
        raise Exception(f"An error occurred while replaying the crew: {e}")


def test():
    """
    Test the crew execution and returns the results.
    """
    try:
        CryptoscopeCrew().crew().test(n_iterations=int(sys.argv[1]), eval_llm=sys.argv[2], inputs={})
    except Exception as e:
        raise Exception(f"An error occurred while testing the crew: {e}")


if __name__ == "__main__":
    run()
