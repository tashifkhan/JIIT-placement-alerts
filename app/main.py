import requests
from pydantic import BaseModel
from dotenv import load_dotenv
import json
import os


load_dotenv()


class LoginResponse(BaseModel):
    userId: int
    username: str
    name: str
    emailHash: str
    sessionKey: str
    uuid: str
    refreshToken: str
    userProfilePhotoId: str
    userModes: list[str]
    permissions: list[str]
    emailVerified: bool
    message: str | None
    enableMfa: bool


def login(email: str | None, password: str | None) -> LoginResponse:
    if not email or not password:
        raise ValueError(
            "Email and password must be provided",
        )

    url = "https://app.joinsuperset.com/tnpsuite-core/login"

    payload = json.dumps(
        {
            "username": email,
            "password": password,
        }
    )

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:141.0) Gecko/20100101 Firefox/141.0",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.5",
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "Referer": "https://app.joinsuperset.com/students/login",
        "x-requester-client": "webapp",
        "x-superset-tenant-id": "jaypee_in_in_it_16",
        "x-superset-tenant-type": "STUDENT",
        "Content-Type": "application/json",
        "Origin": "https://app.joinsuperset.com",
        "DNT": "1",
        "Sec-GPC": "1",
        "Connection": "keep-alive",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
        "TE": "trailers",
    }
    response = requests.post(
        url,
        headers=headers,
        data=payload,
    )
    return LoginResponse(**response.json())

    return notices_sorted


def main():
    email = os.getenv("EMAIL")
    password = os.getenv("ENCRYPTION_PASSWORD")
    response = login(email, password)
    print(json.dumps(response.dict(), indent=4))


if __name__ == "__main__":
    main()
