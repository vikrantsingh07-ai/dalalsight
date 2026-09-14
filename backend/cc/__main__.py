"""Start the Command Center: ``python -m cc`` (from the ``backend`` directory or with the package installed)."""

from __future__ import annotations

import logging

import uvicorn

from .config import LOOPBACK_HOSTS, EnvConfig, load_environment


def main() -> None:
    load_environment()
    env = EnvConfig.from_env()
    if env.host not in LOOPBACK_HOSTS and not env.access_token:
        # Without a token, anyone who can reach the host could change settings, place paper orders and spend the AI budget.
        raise SystemExit(f"Refusing to listen on {env.host}: set CC_ACCESS_TOKEN to a long random string first.")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    from .api.app import create_app

    uvicorn.run(create_app(env), host=env.host, port=env.port, log_level="info", ws_ping_interval=20)


if __name__ == "__main__":
    main()
