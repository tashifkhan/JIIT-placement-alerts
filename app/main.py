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
        reverse=True,
    )
    return notices_sorted


def get_job_details(user: LoginResponse, job_id: str) -> dict:
    if not user or not user.uuid or not user.sessionKey:
        raise ValueError(
            "User must be logged in to fetch job details",
        )

    if not job_id:
        raise ValueError(
            "Job ID must be provided to fetch job details",
        )

    url = f"https://app.joinsuperset.com/tnpsuite-core/students/{user.uuid}/job_profiles/{job_id}"

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
    }

    response = requests.get(
        url,
        params=params,
        headers=headers,
    )

    return response.json()


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
        reverse=True,
    )
    for job in job_listings_sorted:
        job_id = job.get("jobProfileIdentifier")
        if job_id:
            job["jobDetails"] = get_job_details(user, job_id)
    return job_listings_sorted


def main():
    email = os.getenv("EMAIL")
    password = os.getenv("ENCRYPTION_PASSWORD")
    response = login(email, password)
    print(f"Logged in as {response.name} ({response.username})")

    os.makedirs("data", exist_ok=True)

    notices = get_notices(response)
    with open("data/notices.json", "w") as f:
        json.dump(notices, f, indent=4)
    print("Notices saved to data/notices.json")

    job_listings = get_job_listings(response)
    with open("data/job_listings.json", "w") as f:
        json.dump(job_listings, f, indent=4)
    print("Job listings saved to data/job_listings.json")


if __name__ == "__main__":
    main()
