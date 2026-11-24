import argparse
from getpass import getpass
import sys
from typing import Sequence

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.database import get_session_factory
from app.core.security import validate_password_policy
from app.services.auth import DuplicateEmailError, create_initial_admin


def prompt_admin_details(
    email: str | None = None,
    full_name: str | None = None,
) -> tuple[str, str, str]:
    resolved_email = (email or input("Admin email: ")).strip()
    resolved_name = (full_name or input("Full name: ")).strip()

    password = getpass("Password: ")
    confirm_password = getpass("Confirm password: ")
    if password != confirm_password:
        raise ValueError("Passwords do not match.")

    validate_password_policy(password)
    return resolved_email, resolved_name, password


def run_create_admin(
    *,
    db: Session,
    email: str | None = None,
    full_name: str | None = None,
) -> int:
    try:
        resolved_email, resolved_name, password = prompt_admin_details(
            email=email,
            full_name=full_name,
        )
        admin = create_initial_admin(
            db,
            email=resolved_email,
            full_name=resolved_name,
            password=password,
        )
    except (ValueError, ValidationError, DuplicateEmailError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"Created administrator account for {admin.email} (id={admin.id}).")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.cli.create_admin",
        description="Bootstrap the initial EnergyGrid administrator account interactively.",
    )
    parser.add_argument("--email", help="Administrator email address")
    parser.add_argument("--full-name", help="Administrator full name")
    args = parser.parse_args(argv)

    session_factory = get_session_factory()
    with session_factory() as db:
        return run_create_admin(
            db=db,
            email=args.email,
            full_name=args.full_name,
        )


if __name__ == "__main__":
    raise SystemExit(main())
