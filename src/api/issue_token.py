"""簽發 API 用的 JWT。

用法：
    python -m src.api.issue_token --sub alice [--days 30]
"""
import argparse
import time

import jwt

from .settings import settings


def main() -> None:
    parser = argparse.ArgumentParser(description="簽發 API JWT")
    parser.add_argument("--sub", required=True, help="使用者識別，會成為 trace 的 user_id")
    parser.add_argument("--days", type=int, default=30)
    args = parser.parse_args()

    secret = settings.API_JWT_SECRET
    if len(secret.encode()) < 32:
        raise SystemExit(
            "API_JWT_SECRET 未設定或不足 32 bytes。請先產生並寫入 .env：\n"
            '  python -c "import secrets; print(secrets.token_urlsafe(32))"'
        )
    now = int(time.time())
    claims = {"sub": args.sub, "iat": now, "exp": now + args.days * 86400}
    print(jwt.encode(claims, secret, algorithm=settings.API_JWT_ALG))


if __name__ == "__main__":
    main()
