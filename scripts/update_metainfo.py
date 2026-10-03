"""Adds release notes in Markdown to metainfo.xml, in the XML format used by application stores."""

import argparse
import re
import xml.etree.ElementTree as ET
from datetime import datetime


def update_metainfo(version, notes):
    """
    Update the metainfo.xml file by adding a new release.

    Args:
        version: The new version, with or without a leading "v".
        notes: The release notes in Markdown format.
    """
    metainfo_path = "share/metainfo/io.github.mall0r.Twinverse.metainfo.xml"

    try:
        tree = ET.parse(metainfo_path)
        root = tree.getroot()
    except ET.ParseError as e:
        print(f"Error parsing {metainfo_path}: {e}")
        return

    releases_tag = root.find("releases")
    if releases_tag is None:
        releases_tag = ET.SubElement(root, "releases")

    new_release = ET.Element("release")
    new_release.set("version", version.lstrip("v"))
    new_release.set("date", datetime.now().strftime("%Y-%m-%d"))

    if "beta" in version or "alpha" in version or "rc" in version:
        new_release.set("type", "development")
    else:
        new_release.set("type", "stable")

    releases_tag.insert(0, new_release)

    description = ET.SubElement(new_release, "description")

    if notes:
        lines = notes.strip().split("\n")

        start_index = 0
        if lines and re.match(r"^\[\d+\.\d+\.\d+\]\(.*?\)\s*\(\d{4}-\d{2}-\d{2}\)", lines[0]):
            start_index = 1

        current_list = None
        for line in lines[start_index:]:
            line = line.strip()
            if not line:  # Skip empty lines
                current_list = None  # Reset list context on empty line
                continue

            header_match = re.match(r"^(#+)\s*(.*)", line)
            if header_match:
                p = ET.SubElement(description, "p")
                b = ET.SubElement(p, "b")
                b.text = header_match.group(2).strip()
                current_list = None  # Reset list context after a header
            elif line.startswith("* ") or line.startswith("- "):
                if current_list is None:
                    current_list = ET.SubElement(description, "ul")
                li = ET.SubElement(current_list, "li")
                clean_line = re.sub(r"\s*\(\[.*?\]\(.*?\)\)", "", line[2:].strip())  # Remove [text](link) format
                clean_line = re.sub(r"\s*\([a-f0-9]{7,}\)", "", clean_line)  # Remove (hash) format
                clean_line = re.sub(
                    r"\s*\[.*?\]\(.*?\)", "", clean_line
                )  # Remove [text](link) format without parentheses
                clean_line = clean_line.replace("**", "")  # Remove markdown bold
                li.text = clean_line.strip()
            else:
                p = ET.SubElement(description, "p")
                clean_line = re.sub(r"\s*\(\[.*?\]\(.*?\)\)", "", line.strip())  # Remove [text](link) in parentheses
                clean_line = re.sub(r"\s*\([a-f0-9]{7,}\)", "", clean_line)  # Remove (hash) format
                clean_line = re.sub(r"\s*\[.*?\]\(.*?\)", "", clean_line)  # Remove [text](link) format
                clean_line = clean_line.replace("**", "")  # Remove markdown bold
                p.text = clean_line.strip()
                current_list = None  # Reset list context

    ET.indent(tree, space="  ")
    tree.write(metainfo_path, encoding="UTF-8", xml_declaration=True)
    print(f"Successfully updated {metainfo_path} with a new release entry for version {version}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Update metainfo.xml with new release info.")
    parser.add_argument("--version", required=True, help="The new version (e.g., v1.2.3).")
    parser.add_argument("--notes", help="The release notes (in Markdown).")
    parser.add_argument("--notes-file", help="Path to a file containing the release notes (in Markdown).")
    args = parser.parse_args()

    if args.notes_file:
        with open(args.notes_file, "r", encoding="utf-8") as f:
            notes_content = f.read()
    else:
        notes_content = args.notes

    update_metainfo(args.version, notes_content)
