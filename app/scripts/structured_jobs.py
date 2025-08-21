import os
import json


def main():
    path = os.path.join(
        os.getcwd(),
        "data",
        "job_listings.json",
    )
    category_mapping = {
        1: "High",
        2: "Middle",
        3: "Offer is more than 4.6 lacs",
        4: "six months internship",
    }
    structured_job_listings = []
    with open(path, "r") as f:
        data = f.read()
        json_data = json.loads(data)
        for job in json_data:
            tmp = {}
            tmp["id"] = job.get("jobProfileIdentifier")
            tmp["job_profile"] = job.get("jobProfileTitle", "Mazdur")
            tmp["company"] = job.get("companyName", "??")
            tmp["placement_category_code"] = job.get(
                "placementCategoryLevel", "Unknown"
            )
            tmp["placement_category"] = (
                category_text
                if (category_text := job.get("placementCategoryName"))
                else category_mapping[tmp["placement_category_code"]]
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
                    tmp["eligibility_marks"].append(
                        {"level": level, "criteria": creteria}
                    )

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

                    # Log if no courses found for debugging
                    if not tmp["eligibility_courses"]:
                        print(
                            f"No eligibility courses found for job: {tmp.get('id', 'Unknown')}"
                        )

                if more_details := job_details.get("jobProfile"):
                    if more_details.get("allowGenderFemale"):
                        tmp["allowed_genders"].append("Female")

                    if more_details.get("allowGenderMale"):
                        tmp["allowed_genders"].append("Male")

                    if more_details.get("allowGenderOther"):
                        tmp["allowed_genders"].append("Other")

                    if jd := more_details.get("jobDescription"):
                        tmp["job_description"] = jd + more_details.get(
                            "invitationCustomText", ""
                        )

                    if location := more_details.get("location"):
                        tmp["location"] = location

                    if package := more_details.get("package"):
                        tmp["package"] = package

                    if ctc_info := more_details.get("ctcAdditionalInfo"):
                        tmp["package_info"] = ctc_info

                    if skills := more_details.get("requiredSkills"):
                        tmp["required_skills"].extend(skills)

                    if stages := more_details.get("stages"):
                        max_seq = max(int(stage["sequence"]) for stage in stages)
                        tmp["hiring_flow"] = [None] * max_seq
                        for stage in stages:
                            tmp["hiring_flow"][int(stage["sequence"]) - 1] = stage[
                                "name"
                            ]

                    if not package:
                        if ctc := more_details.get("ctcMin"):
                            tmp["package"] = ctc

                if tmp["location"] == "Unknown":
                    if location := job_details.get("jobProfileLocation"):
                        tmp["location"] = location

                tmp["placement_type"] = job_details.get("positionType", "")

            structured_job_listings.append(tmp)

    save_path = os.path.join(
        os.getcwd(),
        "data",
        "structured_job_listings.json",
    )

    with open(save_path, "w") as f:
        json.dump(structured_job_listings, f, indent=4)


def check_len():
    path = os.path.join(
        os.getcwd(),
        "data",
        "structured_job_listings.json",
    )
    with open(path, "r") as f:
        data = f.read()
        json_data = json.loads(data)
        print(f"Total jobs: {len(json_data)}")


if __name__ == "__main__":
    check_len()
