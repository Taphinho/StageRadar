import argparse
import asyncio
import json
import logging

from stageradar.config import Settings
from stageradar.database import open_database, upgrade
from stageradar.runtime import exclusive_instance, running


async def collect(settings: Settings) -> None:
    async with running(settings.model_copy(update={"run_scheduler": False})) as runtime:
        results = await runtime.collection.run()
        print(json.dumps(results, ensure_ascii=False))
        if any(result["status"] == "failed" for result in results):
            raise SystemExit(1)


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m stageradar")
    parser.add_argument("command", choices=["init", "collect"])
    args = parser.parse_args()
    settings = Settings()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.CRITICAL)
    if args.command == "collect":
        asyncio.run(collect(settings))
        return
    with exclusive_instance(settings.data_dir):
        engine = open_database(settings.data_dir)
        try:
            upgrade(engine)
        finally:
            engine.dispose()
    print("Base StageRadar initialisée.")


if __name__ == "__main__":
    main()
