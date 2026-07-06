"""PyInstaller entry point for the graphical client (see `make build-clients`)."""

from wg_client.gui import main

if __name__ == "__main__":
    raise SystemExit(main())
