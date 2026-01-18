"""
SuperSet API Client Service

Implements IScraperClient protocol for interacting with SuperSet APIs.
Wraps the existing SupersetClient functionality.
"""

import os
import json
import logging
import base64
import rsa
from typing import List, Optional, Union, Any

import requests
from pydantic import BaseModel


class User(BaseModel):
    """SuperSet user session model"""

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
    """Notice data model"""

    id: str
    title: str
    content: str
    author: str
    updatedAt: int
    createdAt: int


class EligibilityMark(BaseModel):
    """Eligibility mark criteria"""

    level: str
    criteria: float


class Document(BaseModel):
    """Job document attachment"""

    name: str
    identifier: str
    url: Optional[str] = None


class Job(BaseModel):
    """Structured job listing model"""

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
    annum_months: Optional[str]
    package_info: str
    required_skills: List[str]
    hiring_flow: List[str]
    placement_type: Optional[str] = None
    documents: List[Document] = []


class SupersetClientService:
    """
    SuperSet API client implementing IScraperClient protocol.

    Handles:
    - User authentication
    - Fetching notices
    - Fetching job listings with details
    """

    BASE_URL = "https://app.joinsuperset.com/tnpsuite-core"
    PUBLIC_KEY = """'
    -----BEGIN PUBLIC KEY-----
MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQCgFGVfrY4jQSoZQWWygZ83roKXWD4YeT2x2p41dGkPixe73rT2IW04glagN2vgoZoHuOPqa5and6kAmK2ujmCHu6D1auJhE2tXP+yLkpSiYMQucDKmCsWMnW9XlC5K7OSL77TXXcfvTvyZcjObEz6LIBRzs6+FqpFbUO9SJEfh6wIDAQAB
-----END PUBLIC KEY-----"""

    def __init__(
        self,
        tenant_id: str = "jaypee_in_in_it_16",
        tenant_type: str = "STUDENT",
    ):
        """
        Initialize SuperSet client.

        Args:
            tenant_id: SuperSet tenant identifier
            tenant_type: User type (STUDENT)
        """
        self.logger = logging.getLogger(self.__class__.__name__)
        self.tenant_id = tenant_id
        self.tenant_type = tenant_type
        self.logger.info("SupersetClientService initialized")

    def _common_headers(self) -> dict:
        """Get common request headers"""
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
        """
        Login to SuperSet and return user session.

        Args:
            email: User email
            password: User password

        Returns:
            User session object
        """
        if not email or not password:
            raise ValueError("Email and password must be provided")

        url = f"{self.BASE_URL}/login"

        pubkey = rsa.PublicKey.load_pkcs1_openssl_pem(self.PUBLIC_KEY.encode())
        encrypted_pass = rsa.encrypt(password.encode(), pubkey)
        encrypted_password = base64.b64encode(encrypted_pass).decode()

        payload = json.dumps({"username": email, "password": encrypted_password})
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

        self.logger.info(f"Logged in successfully as {email}")
        return User(**response.json())

    def login_multiple(self, credentials: List[dict]) -> List[User]:
        """
        Login multiple users.

        Args:
            credentials: List of dicts with 'email' and 'password'

        Returns:
            List of successfully logged in User objects
        """
        users = []
        for cred in credentials:
            email = cred.get("email")
            password = cred.get("password")

            try:
                user = self.login(email, password)
                users.append(user)

            except Exception as e:
                self.logger.error(f"Failed to login {email}: {e}")

        self.logger.info(
            f"Successfully logged in {len(users)}/{len(credentials)} users"
        )
        return users

    def get_notices(
        self,
        users: Union[User, List[User]],
        num_posts: int = 10000,
    ) -> List[Notice]:
        """
        Fetch notices from SuperSet.

        Args:
            users: User session(s) to use for fetching
            num_posts: Maximum number of notices to fetch

        Returns:
            List of Notice objects
        """
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

        # Sort by last modified
        notices_sorted = sorted(
            final_notices,
            key=lambda x: x.get("lastModifiedOn", 0),
            reverse=True,
        )

        # Structure into Notice objects
        structured_notices: List[Notice] = []
        for notice in notices_sorted:
            tmp = {
                "id": notice.get("identifier"),
                "title": notice.get("title", "Notice"),
                "content": notice.get("content", ""),
                "author": notice.get("lastModifiedByUserName", ""),
                "updatedAt": notice.get("lastModifiedOn") or notice.get("publishedAt"),
                "createdAt": notice.get("publishedAt"),
            }
            structured_notices.append(Notice(**tmp))

        self.logger.info(f"Fetched {len(structured_notices)} notices")
        return structured_notices

    def get_job_details(self, user: User, job_id: str) -> dict:
        """Fetch detailed job information"""
        if not user or not user.uuid or not user.sessionKey:
            raise ValueError("User must be logged in to fetch job details")

        if not job_id:
            raise ValueError("Job ID must be provided")

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

    def get_document_url(
        self,
        user: User,
        job_id: str,
        document_id: str,
    ) -> Optional[str]:
        """Fetch URL for a job document"""
        if not user or not user.uuid or not user.sessionKey:
            raise ValueError("User must be logged in to fetch document URLs")

        if not job_id or not document_id:
            raise ValueError("Job ID and document ID must be provided")

        url = f"{self.BASE_URL}/students/{user.uuid}/job_profiles/{job_id}/documents/{document_id}/url"
        headers = {
            **self._common_headers(),
            "Authorization": f"Custom {user.sessionKey}",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
        }

        try:
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            result = response.json()
            return result.get("url")
        except Exception as e:
            self.logger.warning(f"Error fetching document URL for {document_id}: {e}")
            return None

    @staticmethod
    def structure_job_listing(job: dict) -> Job:
        """Structure raw job data into Job model"""
        category_mapping = {
            1: "High",
            2: "Middle",
            3: "Offer is more than 4.6 lacs",
            4: "Internship",
        }

        tmp: dict = {
            "id": job.get("jobProfileIdentifier"),
            "job_profile": job.get("jobProfileTitle", "Unknown"),
            "company": job.get("companyName", "??"),
            "placement_category_code": job.get("placementCategoryLevel", 0),
            "placement_category": job.get("placementCategoryName")
            or category_mapping.get(job.get("placementCategoryLevel", 0), "Unknown"),
            "content": job.get("content", ""),
            "createdAt": job.get("createdAt"),
            "deadline": job.get("jobProfileApplicationDeadline"),
            "eligibility_marks": [],
            "eligibility_courses": [],
            "allowed_genders": [],
            "job_description": "",
            "location": "Unknown",
            "package": 0,
            "package_info": "",
            "required_skills": [],
            "hiring_flow": [],
            "documents": [],
        }

        job_details = job.get("jobDetails")
        if job_details:
            # Eligibility marks
            for detail in job_details.get("eligibilityCheckResult", {}).get(
                "academicResults", []
            ):
                level = detail.get("level", "UG")
                criteria = detail.get("required", 5 if level == "UG" else 50)
                tmp["eligibility_marks"].append({"level": level, "criteria": criteria})

            # Eligibility courses
            for course in (
                job_details.get("eligibilityCheckResult", {})
                .get("courseCheckResult", {})
                .get("openedForCourses", [])
            ):
                program = course.get("program")
                name = course.get("name")
                if program and name:
                    short_name = program.get("shortName", "Unknown")
                    tmp["eligibility_courses"].append(f"{short_name} - {name}")
                elif name:
                    tmp["eligibility_courses"].append(f"Unknown - {name}")

            if job_details.get("jobProfile"):
                more_details = job_details["jobProfile"]

                # Genders
                if more_details.get("allowGenderFemale"):
                    tmp["allowed_genders"].append("Female")
                if more_details.get("allowGenderMale"):
                    tmp["allowed_genders"].append("Male")
                if more_details.get("allowGenderOther"):
                    tmp["allowed_genders"].append("Other")

                # Description
                if more_details.get("jobDescription"):
                    tmp["job_description"] = more_details.get(
                        "jobDescription", ""
                    ) + more_details.get("invitationCustomText", "")

                # Location
                if more_details.get("location"):
                    tmp["location"] = more_details.get("location")

                # Package
                if more_details.get("package"):
                    tmp["package"] = more_details.get("package")
                    if tmp["package"] is None or tmp["package"] <= 0:
                        tmp["package"] = (
                            more_details.get("ctcMin")
                            or more_details.get("ctcMax")
                            or 0
                        )

                if more_details.get("ctcAdditionalInfo"):
                    tmp["package_info"] = more_details.get("ctcAdditionalInfo")

                tmp["annum_months"] = more_details.get("ctcInterval")

                if more_details.get("requiredSkills"):
                    tmp["required_skills"].extend(more_details.get("requiredSkills"))

                # Hiring flow
                if more_details.get("stages"):
                    stages = more_details.get("stages")
                    max_seq = max(int(stage["sequence"]) for stage in stages)
                    tmp["hiring_flow"] = [None] * max_seq
                    for stage in stages:
                        tmp["hiring_flow"][int(stage["sequence"]) - 1] = stage["name"]

                if not more_details.get("package") and more_details.get("ctcMin"):
                    tmp["package"] = more_details.get("ctcMin")

                # Documents
                documents = more_details.get("documents", [])
                for doc in documents:
                    if doc.get("name") and doc.get("identifier"):
                        tmp["documents"].append(
                            {
                                "name": doc.get("name"),
                                "identifier": doc.get("identifier"),
                                "url": None,
                            }
                        )

            if tmp["location"] == "Unknown" and job_details.get("jobProfileLocation"):
                tmp["location"] = job_details.get("jobProfileLocation")

            tmp["placement_type"] = job_details.get("positionType", "")

        return Job(**tmp)

    def get_job_listings(
        self,
        users: Union[User, List[User]],
        limit: Optional[int] = None,
    ) -> List[Job]:
        """
        Fetch job listings from SuperSet.

        Args:
            users: User session(s) to use
            limit: Maximum number of jobs to fetch

        Returns:
            List of Job objects
        """
        if isinstance(users, User):
            users = [users]

        if not users or not all(user.uuid and user.sessionKey for user in users):
            raise ValueError("User must be logged in to fetch job listings")

        all_job_listings: List[dict] = []
        seen_job_ids = set()

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

            # Deduplicate
            for job in job_listings:
                job_id = job.get("jobProfileIdentifier")
                if job_id and job_id not in seen_job_ids:
                    seen_job_ids.add(job_id)
                    all_job_listings.append(job)

        # Sort by created date
        job_listings_sorted = sorted(
            all_job_listings,
            key=lambda x: x.get("createdAt", 0),
            reverse=True,
        )

        if limit is not None:
            job_listings_sorted = job_listings_sorted[:limit]

        # Fetch details
        detail_user = users[0]
        for job in job_listings_sorted:
            job_id = job.get("jobProfileIdentifier")
            if job_id:
                job["jobDetails"] = self.get_job_details(detail_user, job_id)

        # Structure jobs
        formatted_job_listings: List[Job] = []
        for job in job_listings_sorted:
            structured_job = self.structure_job_listing(job)

            # Fetch document URLs
            job_id = job.get("jobProfileIdentifier")
            if job_id and structured_job.documents:
                for doc in structured_job.documents:
                    if doc.identifier:
                        doc.url = self.get_document_url(
                            detail_user, job_id, doc.identifier
                        )

            formatted_job_listings.append(structured_job)

        self.logger.info(f"Fetched {len(formatted_job_listings)} job listings")
        return formatted_job_listings
