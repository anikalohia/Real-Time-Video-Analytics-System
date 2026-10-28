from processor import EventProcessor, start_metrics


def main():
    start_metrics()
    ep = EventProcessor()
    try:
        ep.run()
    except KeyboardInterrupt:
        ep.running = False


if __name__ == '__main__':
    main()
