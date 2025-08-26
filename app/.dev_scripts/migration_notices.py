import os
import json
from datetime import datetime
from ..modules.formatting import TextFormatter

JSON_PATH = os.path.join(os.path.dirname(__file__), "../data/structured_notices.json")


def migrate_structured_notices():

    formatter = TextFormatter()
    try:
        with open(JSON_PATH, "r", encoding="utf-8") as f:
            notices = json.load(f)
    except Exception as e:
        print(f"Error reading JSON file: {e}")
        return

    mongo_structured = []
    for notice in notices:
        title = notice.get("title", "No Title")
        raw_content = notice.get("raw_content", "")
        author = notice.get("author", "Unknown")
        posted_time = notice.get("posted_time", "")
        content = notice.get("content", "")
        if not content and raw_content:
            content_lines = raw_content.split("\n")
            content = formatter.format_placement_message(content_lines)

        mongo_structured.append(
            {
                "title": title.strip() if title else "No Title",
                "content": content,
                "raw_content": raw_content,
                "author": author.strip() if author else "Unknown",
                "posted_time": posted_time.strip() if posted_time else "",
                "scraped_at": datetime.utcnow().isoformat(),
                "sent_to_telegram": True,
                "created_at": datetime.utcnow().isoformat(),
                "updated_at": datetime.utcnow().isoformat(),
            }
        )

    # Save to new JSON file in the structure of the mongo modal
    out_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "../data/migration_mongo.json"
    )
    try:
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(mongo_structured, f, ensure_ascii=False, indent=2)
        print(f"✅ Saved {len(mongo_structured)} notices to {out_path}")

    except Exception as e:
        print(f"Error writing to {out_path}: {e}")


if __name__ == "__main__":
    migrate_structured_notices()
