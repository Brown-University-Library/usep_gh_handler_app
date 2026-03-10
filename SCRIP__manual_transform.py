# /// script
# requires-python = ">=3.12, <3.13"
# dependencies = [
# "lxml==4.2.3",
# ]
# ///

import argparse
from pathlib import Path

from lxml import etree


def build_parser() -> argparse.ArgumentParser:
    """
    Builds the command-line argument parser.
    Called by: main()
    """
    parser = argparse.ArgumentParser(
        description="Transforms an inscription XML file with an XSL stylesheet.",
    )
    parser.add_argument(
        "--inscription-path",
        required=True,
        help="Path to the source inscription XML file.",
    )
    parser.add_argument(
        "--stylesheet-path",
        required=True,
        help="Path to the XSL stylesheet file.",
    )
    return parser


def read_text_file(file_path: Path) -> str:
    """
    Reads UTF-8 text from a filesystem path.
    Called by: transform_xml()
    """
    file_text = file_path.read_text(encoding="utf-8")
    return file_text


def transform_xml(inscription_path: Path, stylesheet_path: Path) -> str:
    """
    Applies an XSL transformation to an inscription XML document.
    Called by: main()
    """
    xml_text = read_text_file(inscription_path)
    xsl_text = read_text_file(stylesheet_path)
    xml_dom_obj = etree.fromstring(xml_text.encode("utf-8"))
    transformer_obj = etree.XSLT(etree.fromstring(xsl_text.encode("utf-8")))
    transformed_xml_dom_obj = transformer_obj(xml_dom_obj)
    transformed_xml_utf8 = etree.tostring(
        transformed_xml_dom_obj,
        pretty_print=True,
        encoding="utf-8",
    )
    transformed_xml_text = transformed_xml_utf8.decode("utf-8")
    return transformed_xml_text


def main() -> None:
    """
    Parses arguments, runs the transformation, and prints the result.
    Called by: __main__
    """
    parser = build_parser()
    args = parser.parse_args()
    inscription_path = Path(args.inscription_path)
    stylesheet_path = Path(args.stylesheet_path)
    transformed_xml_text = transform_xml(inscription_path, stylesheet_path)
    print(transformed_xml_text)


if __name__ == "__main__":
    main()
