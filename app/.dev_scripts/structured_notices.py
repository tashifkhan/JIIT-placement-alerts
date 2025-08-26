import os
import json


def main():
    path = os.path.join(
        os.getcwd(),
        "data",
        "notices.json",
    )
    with open(path, "r") as f:
        data = f.read()
        json_data = json.loads(data)
        structured_notices = []
        for notice in json_data:
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
            structured_notices.append(tmp)

    save_path = os.path.join(
        os.getcwd(),
        "data",
        "structured_notices.json",
    )

    with open(save_path, "w") as f:
        json.dump(structured_notices, f, indent=4)


if __name__ == "__main__":
    main()
