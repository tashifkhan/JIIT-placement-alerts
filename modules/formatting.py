import re
import os


class TextFormatter:
    def __init__(self):
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        output_dir = os.path.join(project_root, "output")

        if not os.path.exists(output_dir):
            os.makedirs(output_dir)

        self.input_file = os.path.join(output_dir, "job_posts.txt")
        self.output_file = os.path.join(output_dir, "formatted_job_posts.md")

    def format_content(self):
        """Main method to format the extracted content"""
        try:
            with open(self.input_file, "r", encoding="utf-8") as f:
                content = f.read()

            if not content.strip():
                print("No content to format")
                return False

            # Split content into blocks
            blocks = content.split("=== Content Block")
            formatted_blocks = []

            for i, block in enumerate(blocks):
                if not block.strip():
                    continue

                # Skip the first empty block
                if i == 0 and not block.strip():
                    continue

                # Clean up the block
                block = block.strip()

                # Extract block number and content
                lines = block.split("\n")
                if len(lines) < 2:
                    continue

                # Remove the block number line and "==="
                content_lines = []
                start_content = False

                for line in lines:
                    if line.strip().startswith("===") or line.strip().endswith("==="):
                        continue
                    if line.strip().isdigit():
                        continue
                    start_content = True
                    content_lines.append(line)

                if not content_lines:
                    continue

                # Format the content
                formatted_block = self.format_placement_message(content_lines)
                if formatted_block:
                    formatted_blocks.append(formatted_block)

            # Join all formatted blocks with proper Markdown separators
            final_content = "\n\n---\n\n".join(formatted_blocks)

            with open(self.output_file, "w", encoding="utf-8") as f:
                f.write(final_content)

            print(
                f"Content formatted and saved to {self.output_file} ({len(formatted_blocks)} messages processed)"
            )
            return True

        except Exception as e:
            print(f"Error during text formatting: {e}")
            return False

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
            result = self.clean_extra_newlines(result)

            return result

        except Exception as e:
            print(f"Error formatting message: {e}")
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
        return "http" in line.lower() or "www." in line.lower()

    def clean_extra_newlines(self, text):
        """Clean up excessive newlines"""
        # Replace multiple newlines with maximum of 2
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()
