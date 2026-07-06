"""PyInstaller entry point for the command-line client (see `make build-clients`)."""

from wg_client.main import cli

if __name__ == "__main__":
    cli()
