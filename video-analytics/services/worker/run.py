from detector import DetectionWorker, start_metrics


def main():
    start_metrics()
    w = DetectionWorker()
    try:
        w.run()
    except KeyboardInterrupt:
        w.running = False


if __name__ == "__main__":
    main()
