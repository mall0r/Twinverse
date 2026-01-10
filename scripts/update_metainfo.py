import argparse
import re
import xml.etree.ElementTree as ET
from datetime import datetime


def update_metainfo(version, notes):
    """
    Updates the metainfo.xml file by adding a new release.

    Args:
        version (str): The new version string (e.g., "v1.2.3").
        notes (str): The release notes in Markdown format.
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

    # Create new release element
    new_release = ET.Element("release")
    new_release.set("version", version.lstrip("v"))
    new_release.set("date", datetime.now().strftime("%Y-%m-%d"))

    if "beta" in version or "alpha" in version or "rc" in version:
        new_release.set("type", "development")
    else:
        new_release.set("type", "stable")

    # Insert the new release at the beginning of the list
    releases_tag.insert(0, new_release)

    description = ET.SubElement(new_release, "description")

    # Populate with new notes
    if notes:
        current_list = None
        for line in notes.strip().split("\n"):
            line = line.strip()
            if not line:  # Skip empty lines
                current_list = None  # Reset list context on empty line
                continue

            # Handle headers
            header_match = re.match(r"^(#+)\s*(.*)", line)
            if header_match:
                p = ET.SubElement(description, "p")
                b = ET.SubElement(p, "b")
                b.text = header_match.group(2).strip()
                current_list = None  # Reset list context after a header
            # Handle list items
            elif line.startswith("* ") or line.startswith("- "):
                if current_list is None:
                    current_list = ET.SubElement(description, "ul")
                li = ET.SubElement(current_list, "li")
                li.text = line[2:].strip().replace("**", "")  # Remove list marker and markdown bold
            # Handle regular paragraphs or lines not part of a list
            else:
                p = ET.SubElement(description, "p")
                p.text = line.strip().replace("**", "")  # Remove markdown bold
                current_list = None  # Reset list context

    ET.indent(tree, space="  ")
    tree.write(metainfo_path, encoding="UTF-8", xml_declaration=True)
    print(f"Successfully updated {metainfo_path} with a new release entry for version {version}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Update metainfo.xml with new release info.")
    parser.add_argument("--version", required=True, help="The new version (e.g., v1.2.3).")
    parser.add_argument("--notes", required=True, help="The release notes (in Markdown).")
    args = parser.parse_args()

    update_metainfo(args.version, args.notes)
