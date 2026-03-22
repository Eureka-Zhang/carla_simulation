import argparse

import carla


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=2000)
    ap.add_argument("--timeout", type=float, default=20.0)
    args = ap.parse_args()

    client = carla.Client(args.host, args.port)
    client.set_timeout(args.timeout)

    maps = client.get_available_maps()
    print(f"count: {len(maps)}")
    for m in maps:
        print(m)


if __name__ == "__main__":
    main()

