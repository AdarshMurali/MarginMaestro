import argparse

from streaming.schemas import MarketEventType
from streaming.simulator import run_scenario


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Publish a scripted market scenario onto Kafka/Redpanda."
    )
    parser.add_argument("--scenario", required=True, choices=[t.value for t in MarketEventType])
    args = parser.parse_args()
    run_scenario(MarketEventType(args.scenario))


if __name__ == "__main__":
    main()
