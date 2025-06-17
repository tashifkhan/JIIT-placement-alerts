import re
import os
import logging
from datetime import datetime
from .database import MongoDBManager
from .config import safe_print


class TextFormatter:
    def __init__(self):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.db_manager = MongoDBManager()
        self.logger.info("TextFormatter initialized")

    def format_content(self):
        """Main method to enhance formatting of posts in the database"""
        self.logger.info("Starting content formatting enhancement")
        try:
            # Get all posts that need formatting enhancement
            posts = self.db_manager.collection.find(
                {"sent_to_telegram": {"$ne": True}}
            ).sort("created_at", 1)

            posts_list = list(posts)
            if not posts_list:
                msg = "No posts found to format"
                safe_print(msg)
                self.logger.info(msg)
                return {
                    "success": True,
                    "new_posts": 0,
                    "total_processed": 0,
                }

            enhanced_count = 0
            total_processed = len(posts_list)

            self.logger.info(f"Found {total_processed} posts to process for formatting")

            for post in posts_list:
                try:
                    # Check if post needs enhanced formatting
                    current_content = post.get("content", "")
                    raw_content = post.get("raw_content", "")

                    if raw_content:
                        # Apply enhanced formatting
                        content_lines = raw_content.split("\n")
                        enhanced_content = self.format_placement_message(content_lines)

                        # Only update if enhanced content is significantly different or better
                        if enhanced_content and enhanced_content != current_content:
                            # Update the post with enhanced formatting
                            result = self.db_manager.collection.update_one(
                                {"_id": post["_id"]},
                                {
                                    "$set": {
                                        "content": enhanced_content,
                                        "updated_at": datetime.utcnow(),
                                    }
                                },
                            )

                            if result.modified_count > 0:
                                enhanced_count += 1
                                title = post.get("title", "No Title")
                                success_msg = (
                                    f"✅ Enhanced formatting for: {title[:50]}..."
                                )
                                safe_print(success_msg)
                                self.logger.debug(success_msg)

                except Exception as post_error:
                    error_msg = f"Error processing post {post.get('_id')}: {post_error}"
                    safe_print(error_msg)
                    self.logger.error(error_msg, exc_info=True)
                    continue

            summary_msg = f"📝 Formatting enhancement completed: Posts processed: {total_processed}, Posts enhanced: {enhanced_count}"
            safe_print(f"📝 Formatting enhancement completed:")
            safe_print(f"   Posts processed: {total_processed}")
            safe_print(f"   Posts enhanced: {enhanced_count}")
            self.logger.info(summary_msg)

            return {
                "success": True,
                "new_posts": enhanced_count,
                "total_processed": total_processed,
            }

        except Exception as e:
            error_msg = f"Error during text formatting: {e}"
            safe_print(error_msg)
            self.logger.error(error_msg, exc_info=True)
            return {"success": False, "error": str(e)}

    def extract_post_metadata(self, content_lines):
        """Extract title, author, and posted time from content lines"""
        title = "No Title"
        author = ""
        posted_time = ""

        for line in content_lines[:10]:  # Check first 10 lines for metadata
            line = line.strip()

            # Extract title (look for job posting patterns)
            if self.is_title_line(line) and title == "No Title":
                title = line[:100]  # Limit title length

            # Extract author
            if self.is_author_line(line):
                author = line

            # Extract time
            if self.is_time_line(line):
                posted_time = line

        return title, author, posted_time

    def format_placement_message(self, content_lines):
        """Format individual placement cell message for better readability"""
        try:
            if not content_lines:
                return ""

            formatted_lines = []
            current_section = ""

            for line in content_lines:
                line = line.strip()
                if not line:
                    continue

                # Skip "See Less" at the end
                if line == "See Less":
                    continue

                # Remove the · symbol
                if line.strip() == "·":
                    continue

                # Detect and format different sections
                if self.is_title_line(line):
                    formatted_lines.append(f"\n## {line.title()}\n")

                elif self.is_author_line(line):
                    formatted_lines.append(f"**Posted by:** {line}")

                elif self.is_time_line(line):
                    # Clean up time line by removing · symbol
                    cleaned_line = line.replace("·", "").strip()
                    if cleaned_line:
                        formatted_lines.append(f"**Time:** {cleaned_line}")
                        formatted_lines.append("")

                elif self.is_section_header(line):
                    formatted_lines.append(f"\n**{line.title()}:**")
                    current_section = line.lower()

                elif self.is_deadline_line(line):
                    formatted_lines.append(f"\n**⚠️ DEADLINE:** {line}")

                elif self.is_eligibility_item(line):
                    formatted_lines.append(f"- {line}")

                elif self.is_process_stage(line):
                    formatted_lines.append(f"- {line}")

                elif self.is_link_line(line):
                    formatted_lines.append(f"\n**Link:** {line}")

                elif line.startswith("Click here") or "register" in line.lower():
                    formatted_lines.append(f"\n> {line}")

                else:
                    # Regular content
                    if len(line) > 100:
                        # Long paragraphs - split into readable chunks
                        formatted_lines.append(f"\n{line}\n")
                    else:
                        formatted_lines.append(line)

            # Clean up extra newlines and join
            result = "\n".join(formatted_lines)

            # Extract and add links on the next line
            result = self.extract_and_add_links(result)

            # Clean up extra newlines
            result = self.clean_extra_newlines(result)

            return result

        except Exception as e:
            safe_print(f"Error formatting message: {e}")
            return "\n".join(content_lines)

    def is_title_line(self, line):
        """Check if line is a main title/heading - only for job titles and main announcements"""
        # Only match lines that are clearly job titles or main announcements
        main_title_patterns = [
            "open for applications -",
            "hiring challenge",
            "placement cycle",
            "hackathon",
            "campus connect",
            "virtual tech session",
        ]

        # Must be a substantial line and match main title patterns
        return (
            any(pattern in line.lower() for pattern in main_title_patterns)
            and len(line) > 30
            and not line.lower().startswith("the ")
            and not line.lower().startswith("all ")
            and not line.lower().startswith("students ")
        )

    def is_author_line(self, line):
        """Check if line contains author name"""
        author_names = [
            "anurag srivastava",
            "anita marwaha",
            "vinod kumar",
            "archita kumar",
            "deeksha jain",
        ]
        return any(name in line.lower() for name in author_names)

    def is_time_line(self, line):
        """Check if line contains time information"""
        time_keywords = ["days ago", "hours ago", "minutes ago", "yesterday", "today"]
        return any(keyword in line.lower() for keyword in time_keywords)

    def is_section_header(self, line):
        """Check if line is a section header"""
        headers = [
            "eligibility",
            "applicable courses",
            "hiring process",
            "webinar details",
            "key dates",
            "benefits",
            "guidelines",
        ]
        return any(header in line.lower() for header in headers) and len(line) < 50

    def is_deadline_line(self, line):
        """Check if line contains deadline information"""
        return "deadline" in line.lower() or (
            "applications is" in line.lower()
            and any(
                month in line.lower()
                for month in [
                    "january",
                    "february",
                    "march",
                    "april",
                    "may",
                    "june",
                    "july",
                    "august",
                    "september",
                    "october",
                    "november",
                    "december",
                ]
            )
        )

    def is_eligibility_item(self, line):
        """Check if line is an eligibility criteria"""
        eligibility_patterns = [
            "class 10th",
            "class 12th",
            "undergraduate",
            "post graduate",
            "cgpa",
            "percent",
            "b.tech",
            "m.tech",
            "integrated",
            "no backlogs",
        ]
        return (
            any(pattern in line.lower() for pattern in eligibility_patterns)
            and len(line) < 80
        )

    def is_process_stage(self, line):
        """Check if line is a hiring process stage"""
        process_stages = [
            "online test",
            "technical interview",
            "hr interview",
            "written test",
            "group discussion",
            "aptitude test",
            "resume screening",
        ]
        return any(stage in line.lower() for stage in process_stages) and len(line) < 80

    def is_link_line(self, line):
        """Check if line contains a URL"""
        # Check for standard URL patterns
        if "http" in line.lower() or "www." in line.lower():
            return True

        # Check for subdomain patterns like apple.adobe or hiring.justpay
        subdomain_pattern = re.compile(
            r"([a-zA-Z0-9][-a-zA-Z0-9]*\.[a-zA-Z0-9][-a-zA-Z0-9\.]*\.[a-zA-Z]{2,}|\b[a-zA-Z0-9][-a-zA-Z0-9]*\.[a-zA-Z]{2,})"
        )
        matches = subdomain_pattern.findall(line.lower())

        # Filter out common false positives
        for match in matches:
            if (
                not re.match(r"^\d+\.\d+$", match)  # Not version numbers
                and not re.match(r"^\d+\.\d+\.\d+$", match)  # Not version numbers
                and not re.match(r"^\d{1,2}\.\d{1,2}\.\d{2,4}$", match)  # Not dates
                and not match.endswith(".png")  # Not image extensions
                and not match.endswith(".jpg")
                and not match.endswith(".jpeg")
                and not match.endswith(".gif")
            ):
                return True

        return False

    def extract_and_add_links(self, text):
        """Extract links from text and add them on the next line

        This function extracts URLs from text that might be embedded in HTML tags,
        or preceded by text like "Click here" or similar call to action text.
        It also handles subdomain-only URLs like "apple.adobe" or "hiring.justpay".
        The extracted links are then added on a new line after the original text.
        """
        # Regular expression to find standard URLs in text
        url_pattern = re.compile(r'(https?://[^\s<>"]+|www\.[^\s<>"]+)')

        # Regular expression for subdomain-only URLs (like apple.adobe or hiring.justpay)
        # Matches domain patterns that have at least one dot and don't have spaces or common punctuation
        subdomain_pattern = re.compile(
            r"([a-zA-Z0-9][-a-zA-Z0-9]*\.[a-zA-Z0-9][-a-zA-Z0-9\.]*\.[a-zA-Z]{2,}|\b[a-zA-Z0-9][-a-zA-Z0-9]*\.[a-zA-Z]{2,})"
        )

        # Regular expression to find HTML anchor tags
        html_link_pattern = re.compile(
            r'<a\s+(?:[^>]*?\s+)?href=["\'](.*?)["\'].*?>(.*?)<\/a>', re.IGNORECASE
        )

        # Process each line
        lines = text.split("\n")
        result_lines = []

        for line in lines:
            line_trimmed = line.strip()
            if not line_trimmed:
                result_lines.append(line)
                continue

            result_lines.append(line)

            # Check if the line is just a standalone URL
            if url_pattern.fullmatch(line_trimmed) or subdomain_pattern.fullmatch(
                line_trimmed
            ):
                continue  # Skip adding duplicate if it's already a standalone URL

            # Check for HTML links
            html_matches = html_link_pattern.findall(line)
            if html_matches:
                for url, link_text in html_matches:
                    if url:  # Always extract URLs from HTML tags
                        result_lines.append(url)
                continue  # Skip other checks for this line

            # Look for standard URLs in the text
            matches = url_pattern.findall(line)
            if matches:
                for url in matches:
                    result_lines.append(url)
                continue  # Skip subdomain check if we found standard URLs

            # Look for subdomain-only URLs
            subdomain_matches = subdomain_pattern.findall(line)
            for domain in subdomain_matches:
                # Filter out common false positives like "v1.0" or dates like "17.06.2023"
                if (
                    not re.match(r"^\d+\.\d+$", domain)  # Not version numbers
                    and not re.match(r"^\d+\.\d+\.\d+$", domain)  # Not version numbers
                    and not re.match(
                        r"^\d{1,2}\.\d{1,2}\.\d{2,4}$", domain
                    )  # Not dates
                    and not domain.endswith(".png")  # Not image extensions
                    and not domain.endswith(".jpg")
                    and not domain.endswith(".jpeg")
                    and not domain.endswith(".gif")
                ):
                    result_lines.append(domain)

        return "\n".join(result_lines)

    def clean_extra_newlines(self, text):
        """Clean up excessive newlines"""
        # Replace multiple newlines with maximum of 2
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()
