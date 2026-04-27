from __future__ import annotations

import logging
import os
import threading

import uvicorn

from rca_engine.api import create_app
from rca_engine.config import load_settings
from rca_engine.workers.kafka_worker import KafkaRCAWorker


def main() -> None:
    logging.basicConfig(
        level=os.getenv("RCA_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    settings = load_settings()
    mode = os.getenv("RCA_MODE", "all").lower()

    if mode in {"worker", "all"}:
        worker = KafkaRCAWorker(settings)
        if mode == "worker":
            worker.run_forever()
            return
        thread = threading.Thread(target=worker.run_forever, name="kafka-rca-worker", daemon=True)
        thread.start()

    if mode in {"api", "all"}:
        uvicorn.run(
            create_app(settings),
            host=settings.api_host,
            port=settings.api_port,
            log_level=os.getenv("UVICORN_LOG_LEVEL", "info"),
        )
        return

    raise ValueError(f"Unsupported RCA_MODE: {mode}")


if __name__ == "__main__":
    main()
