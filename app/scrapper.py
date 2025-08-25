import requests
from pydantic import BaseModel
from dotenv import load_dotenv
import json
import os
from typing import List, Optional, Union


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
    userModes: List[str]
    permissions: List[str]
    emailVerified: bool
    message: Optional[str]
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
    createdAt: Optional[int]
    deadline: Optional[int]
    eligibility_marks: List[EligibilityMark]
    eligibility_courses: List[str]
    allowed_genders: List[str]
    job_description: str
    location: str
    package: float
    package_info: str
    required_skills: List[str]
    hiring_flow: List[str]
    placement_type: Optional[str] = None


class SupersetClient:
    """Class-based client for interacting with the SuperSet (TNP Suite) APIs."""

    BASE_URL = "https://app.joinsuperset.com/tnpsuite-core"

    def __init__(
        self, tenant_id: str = "jaypee_in_in_it_16", tenant_type: str = "STUDENT"
    ) -> None:
        self.tenant_id = tenant_id
        self.tenant_type = tenant_type

    def _common_headers(self) -> dict:
        return {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:141.0) Gecko/20100101 Firefox/141.0",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.5",
            "Accept-Encoding": "gzip, deflate, br, zstd",
            "x-requester-client": "webapp",
            "x-superset-tenant-id": self.tenant_id,
            "x-superset-tenant-type": self.tenant_type,
            "DNT": "1",
            "Sec-GPC": "1",
            "Connection": "keep-alive",
        }

    def login(self, email: Optional[str], password: Optional[str]) -> User:
        if not email or not password:
            raise ValueError("Email and password must be provided")

        url = f"{self.BASE_URL}/login"
        payload = json.dumps({"username": email, "password": password})
        headers = {
            **self._common_headers(),
            "Referer": "https://app.joinsuperset.com/students/login",
            "Content-Type": "application/json",
            "Origin": "https://app.joinsuperset.com",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
            "TE": "trailers",
        }
        response = requests.post(url, headers=headers, data=payload)
        response.raise_for_status()
        return User(**response.json())

    def get_notices(
        self, users: Union[User, List[User]], num_posts: int = 10000
    ) -> List[Notice]:
        if isinstance(users, User):
            users = [users]

        if any(not user or not user.uuid or not user.sessionKey for user in users):
            raise ValueError("User must be logged in to fetch notices")

        final_notices: List[dict] = []
        for user in users:
            url = f"{self.BASE_URL}/students/{user.uuid}/notices"
            params = {"page": 0, "size": num_posts, "_loader_": "false"}
            headers = {
                **self._common_headers(),
                "Referer": "https://app.joinsuperset.com/students",
                "Authorization": f"Custom {user.sessionKey}",
                "Sec-Fetch-Dest": "empty",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Site": "same-origin",
                "TE": "trailers",
            }
            response = requests.get(url, headers=headers, params=params)
            response.raise_for_status()
            notices = response.json()

            if not final_notices:
                final_notices.extend(notices)
            else:
                for notice in notices:
                    if notice["identifier"] not in [
                        n["identifier"] for n in final_notices
                    ]:
                        final_notices.append(notice)

        notices_sorted = sorted(
            final_notices,
            key=lambda x: x.get("lastModifiedOn", 0),
            reverse=True,
        )

        structured_notices: List[Notice] = []
        for notice in notices_sorted:
            tmp: dict = {}
            tmp["id"] = notice.get("identifier")
            tmp["title"] = notice.get("title", "Notice")
            tmp["content"] = notice.get("content", "")
            tmp["author"] = notice.get("lastModifiedByUserName", "")
            last = notice.get("lastModifiedOn")
            tmp["updatedAt"] = last if last else notice.get("publishedAt")
            tmp["createdAt"] = notice.get("publishedAt")
            structured_notices.append(Notice(**tmp))

        return structured_notices

    def get_job_details(self, user: User, job_id: str) -> dict:
        if not user or not user.uuid or not user.sessionKey:
            raise ValueError("User must be logged in to fetch job details")
        if not job_id:
            raise ValueError("Job ID must be provided to fetch job details")

        url = f"{self.BASE_URL}/students/{user.uuid}/job_profiles/{job_id}"
        params = {"_loader_": "false"}
        headers = {
            **self._common_headers(),
            "Referer": "https://app.joinsuperset.com/students/jobprofiles",
            "Authorization": f"Custom {user.sessionKey}",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
        }
        response = requests.get(url, params=params, headers=headers)
        response.raise_for_status()
        return response.json()

    @staticmethod
    def structure_job_listing(job: dict) -> Job:
        category_mapping = {
            1: "High",
            2: "Middle",
            3: "Offer is more than 4.6 lacs",
            4: "Internship",
        }
        tmp: dict = {}
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

    def get_job_listings(
        self, users: Union[User, List[User]], limit: Optional[int] = None
    ) -> List[Job]:
        if isinstance(users, User):
            users = [users]

        if not users or not all(user.uuid and user.sessionKey for user in users):
            raise ValueError("User must be logged in to fetch job listings")

        all_job_listings: List[dict] = []
        for u in users:
            url = f"{self.BASE_URL}/students/{u.uuid}/job_profiles"
            params = {"_loader_": "false"}
            headers = {
                **self._common_headers(),
                "Referer": "https://app.joinsuperset.com/students/jobprofiles",
                "Authorization": f"Custom {u.sessionKey}",
                "Sec-Fetch-Dest": "empty",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Site": "same-origin",
                "TE": "trailers",
            }
            response = requests.get(url, headers=headers, params=params)
            response.raise_for_status()
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
            all_job_listings, key=lambda x: x.get("createdAt", 0), reverse=True
        )
        if limit is not None:
            job_listings_sorted = job_listings_sorted[:limit]

        # Use the first user to fetch details reliably
        detail_user = users[0]
        for job in job_listings_sorted:
            job_id = job.get("jobProfileIdentifier")
            if job_id:
                job["jobDetails"] = self.get_job_details(detail_user, job_id)

        formatted_job_listings: List[Job] = []
        for job in job_listings_sorted:
            formatted_job_listings.append(self.structure_job_listing(job))
        return formatted_job_listings

    def update_notices(
        self, users: Union[User, List[User]], notices: List[Notice]
    ) -> List[Notice]:
        if isinstance(users, User):
            users = [users]
        if any(not user or not user.uuid or not user.sessionKey for user in users):
            raise ValueError("User must be logged in to fetch notices")

        new_notices = self.get_notices(users, 20)
        for notice in new_notices:
            if notice not in notices:
                notices.append(notice)
        notices_sorted = sorted(notices, key=lambda x: x.createdAt, reverse=True)
        return notices_sorted

    def update_job_listings(
        self, users: Union[User, List[User]], job_listings: List[Job]
    ) -> List[Job]:
        if isinstance(users, User):
            users = [users]
        if any(not user or not user.uuid or not user.sessionKey for user in users):
            raise ValueError("User must be logged in to update job listings")

        new_job_listings = self.get_job_listings(users, limit=20)
        for job in new_job_listings:
            if job not in job_listings:
                job_listings.append(job)
        job_listings_sorted = sorted(
            job_listings,
            key=lambda x: (
                getattr(x, "createdAt", 0)
                if hasattr(x, "createdAt")
                and isinstance(getattr(x, "createdAt", None), (int, float))
                else 0
            ),
            reverse=True,
        )
        return job_listings_sorted


def main():
    client = SupersetClient()

    cse_email = os.getenv("CSE_EMAIL")
    cse_password = os.getenv("CSE_ENCRYPTION_PASSWORD")
    cse_user = client.login(cse_email, cse_password)
    print(f"Logged in as {cse_user.name} ({cse_user.username})")

    ece_email = os.getenv("ECE_EMAIL")
    ece_password = os.getenv("ECE_ENCRYPTION_PASSWORD")
    ece_user = client.login(ece_email, ece_password)
    print(f"Logged in as {ece_user.name} ({ece_user.username})")

    os.makedirs("data", exist_ok=True)

    job_listings = client.get_job_listings([cse_user, ece_user])
    for job in job_listings:
        print(json.dumps(job.model_dump(), indent=4))
    print("Job listings fetched.")


if __name__ == "__main__":
    main()
