import argparse
import os

from ingestion import StreamIngestor, start_metrics


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--stream-id", default=os.getenv("STREAM_ID"))
    parser.add_argument("--source", default=os.getenv("SOURCE_URL"))
    parser.add_argument("--manager", action="store_true",
                        help="run as manager polling DB for running streams")
    args = parser.parse_args()

    start_metrics()

    if args.manager or (not args.source and os.getenv("POSTGRES_DSN")):
        from manager import StreamManager
        mgr = StreamManager()
        try:
            mgr.run()
        except KeyboardInterrupt:
            mgr.running = False
        return

    if not args.source:
        raise SystemExit("No source provided. Set SOURCE_URL or pass --source, or use --manager.")

    ing = StreamIngestor(args.stream_id or "stream1", args.source)
    try:
        ing.run()
    except KeyboardInterrupt:
        ing.running = False


if __name__ == "__main__":
    main()
