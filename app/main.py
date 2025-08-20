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


def get_notices(user: LoginResponse) -> list[dict]:
    if not user or not user.uuid or not user.sessionKey:
        raise ValueError(
            "User must be logged in to fetch notices",
        )

    url = f"https://app.joinsuperset.com/tnpsuite-core/students/{user.uuid}/notices"

    params = {
        "page": 0,
        "size": 1000,
        "_loader_": "false",
    }

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:141.0) Gecko/20100101 Firefox/141.0",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.5",
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "Referer": "https://app.joinsuperset.com/students",
        "Authorization": f"Custom {user.sessionKey}",
        "x-requester-client": "webapp",
        "x-superset-tenant-id": "jaypee_in_in_it_16",
        "x-superset-tenant-type": "STUDENT",
        "DNT": "1",
        "Sec-GPC": "1",
        "Connection": "keep-alive",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
        "TE": "trailers",
    }

    response = requests.get(
        url,
        headers=headers,
        params=params,
    )

    notices = response.json()
    notices_sorted = sorted(
        notices,
        key=lambda x: x.get("lastModifiedOn", 0),
        reverse=False,
    )
    return notices_sorted


def get_job_listings(user: LoginResponse) -> list[dict]:
    if not user or not user.uuid or not user.sessionKey:
        raise ValueError(
            "User must be logged in to fetch job listings",
        )

    url = (
        f"https://app.joinsuperset.com/tnpsuite-core/students/{user.uuid}/job_profiles"
    )

    params = {
        "_loader_": "false",
    }

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:141.0) Gecko/20100101 Firefox/141.0",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.5",
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "Referer": "https://app.joinsuperset.com/students/jobprofiles",
        "Authorization": f"Custom {user.sessionKey}",
        "x-requester-client": "webapp",
        "x-superset-tenant-id": "jaypee_in_in_it_16",
        "x-superset-tenant-type": "STUDENT",
        "DNT": "1",
        "Sec-GPC": "1",
        "Connection": "keep-alive",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
        "TE": "trailers",
    }

    response = requests.get(
        url,
        headers=headers,
        params=params,
    )

    job_listings = response.json()
    job_listings_sorted = sorted(
        job_listings,
        key=lambda x: x.get("createdAt", 0),
        reverse=False,
    )
    return job_listings_sorted


def main():
    email = os.getenv("EMAIL")
    password = os.getenv("ENCRYPTION_PASSWORD")
    response = login(email, password)
    print(json.dumps(response.dict(), indent=4))
    # notices = get_notices(response)
    # print(json.dumps(notices, indent=4))
    job_listings = get_job_listings(response)
    print(json.dumps(job_listings, indent=4))


if __name__ == "__main__":
    main()
