"""Smoke test: confirm penaltyblog imports cleanly and report its version."""

import importlib.metadata

import penaltyblog


def main() -> None:
    version = importlib.metadata.version("penaltyblog")
    print(f"penaltyblog imported OK — version {version}")
    print(f"module location: {penaltyblog.__file__}")


if __name__ == "__main__":
    main()
