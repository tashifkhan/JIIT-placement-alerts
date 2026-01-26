import base64
import argparse
import os
import sys


def convert_to_base64(file_path, include_header=False):
    """
    Reads the file at the given path and returns the base64 encoded string.
    """
    if not os.path.isfile(file_path):
        print(f"Error: The file '{file_path}' does not exist.")
        sys.exit(1)

    try:
        with open(file_path, "rb") as image_file:
            encoded_string = base64.b64encode(image_file.read()).decode("utf-8")

            if include_header:
                # Basic MIME type detection based on extension
                ext = os.path.splitext(file_path)[1].lower().strip(".")
                return f"data:image/{ext};base64,{encoded_string}"

            return encoded_string
    except Exception as e:
        print(f"An error occurred during conversion: {e}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Convert a PNG image to a Base64 string."
    )
    parser.add_argument(
        "path",
        help="The file path to the PNG image.",
    )
    parser.add_argument(
        "-w",
        "--web",
        action="store_true",
        help="Include the Data URI header (e.g., data:image/png;base64,...)",
    )

    args = parser.parse_args()

    result = convert_to_base64(args.path, include_header=args.web)

    # Printing directly to stdout
    print(result)


if __name__ == "__main__":
    main()
