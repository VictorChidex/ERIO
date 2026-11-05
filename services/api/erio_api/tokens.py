"""Admin tool for API tokens (admin-only in the first release, spec step 9).

    python -m erio_api.tokens create --email dev@example.com [--tier free|pro]
    python -m erio_api.tokens list
    python -m erio_api.tokens revoke --id 3

``create`` prints the token once; only its hash is stored, so it cannot be
shown again. Run inside the API container: docker compose exec api python -m erio_api.tokens ...
"""

import argparse
from datetime import UTC, datetime

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from erio_api.access import new_token
from erio_core.db.models import TOKEN_TIERS, ApiToken
from erio_core.settings import get_settings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="erio_api.tokens", description="Manage ERIO API tokens")
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create", help="create a token and print it once")
    create.add_argument("--email", required=True)
    create.add_argument("--tier", choices=TOKEN_TIERS, default="free")
    commands.add_parser("list", help="list tokens (never their values)")
    revoke = commands.add_parser("revoke", help="revoke a token by id")
    revoke.add_argument("--id", type=int, required=True)
    args = parser.parse_args(argv)

    engine = create_engine(get_settings().sqlalchemy_url)
    with Session(engine) as session, session.begin():
        if args.command == "create":
            token, digest = new_token()
            row = ApiToken(owner_email=args.email, token_hash=digest, tier=args.tier)
            session.add(row)
            session.flush()
            print(f"token id {row.id} for {args.email} ({args.tier}). Shown once, store it now:")
            print(token)
        elif args.command == "list":
            for row in session.scalars(select(ApiToken).order_by(ApiToken.id)):
                state = f"revoked {row.revoked_at:%Y-%m-%d}" if row.revoked_at else "active"
                used = f"{row.last_used_at:%Y-%m-%d %H:%M}" if row.last_used_at else "never"
                print(
                    f"{row.id:>4}  {row.owner_email:<32} {row.tier:<5} {state:<18} last used {used}"
                )
        else:
            found = session.get(ApiToken, args.id)
            if found is None:
                print(f"no token {args.id}")
                return 1
            found.revoked_at = found.revoked_at or datetime.now(UTC)
            print(f"token {args.id} revoked")
    engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
