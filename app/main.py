import requests
from pydantic import BaseModel
from dotenv import load_dotenv
import json
import os


load_dotenv()


class User(BaseModel):
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


class Notice(BaseModel):
    id: str
    title: str
    content: str
    author: str
    updatedAt: int
    createdAt: int


class EligibilityMark(BaseModel):
    level: str
    criteria: float


class Job(BaseModel):
    id: str
    job_profile: str
    company: str
    placement_category_code: int
    placement_category: str
    content: str
    createdAt: int | None
    deadline: int | None
    eligibility_marks: list[EligibilityMark]
    eligibility_courses: list[str]
    allowed_genders: list[str]
    job_description: str
    location: str
    package: float
    package_info: str
    required_skills: list[str]
    hiring_flow: list[str]
    placement_type: str | None = None


def login(email: str | None, password: str | None) -> User:
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
    return User(**response.json())


def get_notices(users: User | list[User], num_posts: int = 10000) -> list[Notice]:
    if isinstance(users, User):
        users = [users]

    if any(not user or not user.uuid or not user.sessionKey for user in users):
        raise ValueError(
            "User must be logged in to fetch notices",
        )

    final_notices = []
    for user in users:
        url = f"https://app.joinsuperset.com/tnpsuite-core/students/{user.uuid}/notices"

        params = {
            "page": 0,
            "size": num_posts,
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

        if not final_notices:
            final_notices.extend(notices)
        else:
            for notice in notices:
                if notice["identifier"] not in [n["identifier"] for n in final_notices]:
                    final_notices.append(notice)

    notices_sorted = sorted(
        final_notices,
        key=lambda x: x.get("lastModifiedOn", 0),
        reverse=True,
    )

    structured_notices = []
    for notice in notices_sorted:
        tmp = {}
        tmp["id"] = notice.get("identifier")
        tmp["title"] = notice.get("title", "Notice")
        tmp["content"] = notice.get("content", "")
        tmp["author"] = notice.get("lastModifiedByUserName", "")
        tmp["updatedAt"] = (
            time
            if (time := notice.get("lastModifiedOn"))
            else notice.get("publishedAt")
        )
        tmp["createdAt"] = notice.get("publishedAt")
        structured_notices.append(Notice(**tmp))

    return structured_notices


def get_job_details(user: User, job_id: str) -> dict:
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


def structure_job_listing(job: dict) -> Job:
    category_mapping = {
        1: "High",
        2: "Middle",
        3: "Offer is more than 4.6 lacs",
        4: "six months internship",
    }
    tmp = {}
    tmp["id"] = job.get("jobProfileIdentifier")
    tmp["job_profile"] = job.get("jobProfileTitle", "Mazdur")
    tmp["company"] = job.get("companyName", "??")
    tmp["placement_category_code"] = job.get("placementCategoryLevel", "Unknown")
    tmp["placement_category"] = (
        job.get("placementCategoryName")
        if job.get("placementCategoryName")
        else category_mapping.get(tmp["placement_category_code"], "Unknown")
    )
    tmp["content"] = job.get("content", "")
    tmp["createdAt"] = job.get("createdAt")
    tmp["deadline"] = job.get("jobProfileApplicationDeadline", "")
    job_details = job.get("jobDetails")
    tmp["eligibility_marks"] = []
    tmp["eligibility_courses"] = []
    tmp["allowed_genders"] = []
    tmp["job_description"] = ""
    tmp["location"] = "Unknown"
    tmp["package"] = 0
    tmp["package_info"] = ""
    tmp["required_skills"] = []
    tmp["hiring_flow"] = []

    if job_details:
        for ganda_deatils in job_details.get("eligibilityCheckResult", {}).get(
            "academicResults", []
        ):
            level = ganda_deatils.get("level", "UG")
            creteria = ganda_deatils.get(
                "required", 5 if ganda_deatils.get("level") == "UG" else 50
            )
            tmp["eligibility_marks"].append({"level": level, "criteria": creteria})

        for ganda_details in (
            job_details.get("eligibilityCheckResult", {})
            .get("courseCheckResult", [])
            .get("openedForCourses", [])
        ):
            program = ganda_details.get("program")
            name = ganda_details.get("name")
            if program and name:
                short_name = program.get("shortName", "Unknown")
                tmp["eligibility_courses"].append(f"{short_name} - {name}")
            elif name:
                tmp["eligibility_courses"].append(f"Unknown - {name}")
            else:
                tmp["eligibility_courses"].append("Unknown Course")

        if job_details.get("jobProfile"):
            more_details = job_details["jobProfile"]
            if more_details.get("allowGenderFemale"):
                tmp["allowed_genders"].append("Female")
            if more_details.get("allowGenderMale"):
                tmp["allowed_genders"].append("Male")
            if more_details.get("allowGenderOther"):
                tmp["allowed_genders"].append("Other")
            if more_details.get("jobDescription"):
                tmp["job_description"] = more_details.get(
                    "jobDescription", ""
                ) + more_details.get("invitationCustomText", "")
            if more_details.get("location"):
                tmp["location"] = more_details.get("location")
            if more_details.get("package"):
                tmp["package"] = more_details.get("package")
            if more_details.get("ctcAdditionalInfo"):
                tmp["package_info"] = more_details.get("ctcAdditionalInfo")
            if more_details.get("requiredSkills"):
                tmp["required_skills"].extend(more_details.get("requiredSkills"))
            if more_details.get("stages"):
                stages = more_details.get("stages")
                max_seq = max(int(stage["sequence"]) for stage in stages)
                tmp["hiring_flow"] = [None] * max_seq
                for stage in stages:
                    tmp["hiring_flow"][int(stage["sequence"]) - 1] = stage["name"]
            if not more_details.get("package"):
                if more_details.get("ctcMin"):
                    tmp["package"] = more_details.get("ctcMin")

        if tmp["location"] == "Unknown":
            if job_details.get("jobProfileLocation"):
                tmp["location"] = job_details.get("jobProfileLocation")

        tmp["placement_type"] = job_details.get("positionType", "")

    return Job(**tmp)


def get_job_listings(users: User | list[User]) -> list[Job]:
    if isinstance(users, User):
        users = [users]

    if not users or not all(user.uuid and user.sessionKey for user in users):
        raise ValueError(
            "User must be logged in to fetch job listings",
        )

    all_job_listings = []

    for user in users:
        url = f"https://app.joinsuperset.com/tnpsuite-core/students/{user.uuid}/job_profiles"

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

        if job_listings:
            all_job_listings.extend(job_listings)
        else:
            for job in job_listings:
                if job["jobProfileIdentifier"] not in [
                    j["jobProfileIdentifier"] for j in all_job_listings
                ]:
                    all_job_listings.append(job)

    job_listings_sorted = sorted(
        all_job_listings,
        key=lambda x: x.get("createdAt", 0),
        reverse=True,
    )

    for job in job_listings_sorted:
        job_id = job.get("jobProfileIdentifier")
        if job_id:
            job["jobDetails"] = get_job_details(user, job_id)

    formated_job_listings = []

    for job in job_listings_sorted:
        formated_job_listings.append(structure_job_listing(job))

    return formated_job_listings


def main():
    cse_email = os.getenv("CSE_EMAIL")
    cse_password = os.getenv("CSE_ENCRYPTION_PASSWORD")
    cse_user = login(cse_email, cse_password)
    print(f"Logged in as {cse_user.name} ({cse_user.username})")

    ece_email = os.getenv("ECE_EMAIL")
    ece_password = os.getenv("ECE_ENCRYPTION_PASSWORD")
    ece_user = login(ece_email, ece_password)
    print(f"Logged in as {ece_user.name} ({ece_user.username})")

    os.makedirs("data", exist_ok=True)

    # notices = get_notices([cse_user, ece_user])
    # # with open("data/notices.json", "w") as f:
    # for notice in notices:
    #     print(
    #         json.dumps(
    #             notice.model_dump(),
    #             indent=4,
    #         )
    #     )
    # print("Notices saved to data/notices.json")

    job_listings = get_job_listings([cse_user, ece_user])
    # with open("data/job_listings.json", "w") as f:
    #     json.dump(job_listings, f, indent=4)
    for job in job_listings:
        print(
            json.dumps(
                job.model_dump(),
                indent=4,
            )
        )
    print("Job listings saved to data/job_listings.json")


if __name__ == "__main__":
    main()
