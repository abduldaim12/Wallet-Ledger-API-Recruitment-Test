import os
import sys
from contextlib import closing

from database import connect_db, ensure_schema, ensure_seed


def main() -> None:
    if len(sys.argv) > 1:
        command = sys.argv[1].lower()
        if command == "migrate":
            with closing(connect_db()) as conn:
                ensure_schema(conn)
            print("database schema ready")
            return
        if command == "seed":
            with closing(connect_db()) as conn:
                ensure_schema(conn)
                ensure_seed(conn, int(os.getenv("SEED_ROWS", "10000000")), int(os.getenv("SEED_USERS", "100000")))
            print("seed complete")
            return
        if command in {"help", "--help", "-h"}:
            print("Usage: python main.py [migrate|seed|server]")
            return

    with closing(connect_db()) as conn:
        ensure_schema(conn)
        ensure_seed(conn, int(os.getenv("SEED_ROWS", "10000000")), int(os.getenv("SEED_USERS", "100000")))

    from api import create_app

    app = create_app()
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8080)


if __name__ == "__main__":
    main()
