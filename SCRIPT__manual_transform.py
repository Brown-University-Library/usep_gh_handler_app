# /// script
# requires-python = ">=3.8, <3.9"
# dependencies = [
# "httpx~=0.28.0",
# "lxml~=6.0.2.0",
# ]
# ///


"""
Usage:
    uv run ./SCRIPT__manual_transform.py --inscription-path "/path/or/url/to/inscription.xml" --stylesheet-path "/path/or/url/to/stylesheet.xsl"
    ...or...
    uv run ./SCRIPT__manual_transform.py --inscription-path "https://raw.githubusercontent.com/Brown-University-Library/usep-data/refs/heads/master/xml_inscriptions/metadata_only/CA.Berk.UC.HMA.L.8.71.7767.xml" --stylesheet-path "https://raw.githubusercontent.com/Brown-University-Library/usep-data/refs/heads/master/resources/xsl/USEp_to_Solr.xsl"
    ...or (never run untrusted code!)...
    uv run https://gist.github.com/birkin/3c9705da27f2f1d9864b7f1127d9af9b --inscription-path "https://raw.githubusercontent.com/Brown-University-Library/usep-data/refs/heads/master/xml_inscriptions/metadata_only/CA.Berk.UC.HMA.L.8.71.7767.xml" --stylesheet-path "https://raw.githubusercontent.com/Brown-University-Library/usep-data/refs/heads/master/resources/xsl/USEp_to_Solr.xsl"

Notes:
- either argument can be a path or a URL
- requires `uv` to be installed: <https://docs.astral.sh/uv/getting-started/installation//>
"""

import argparse
import platform
from pathlib import Path
from urllib.parse import urlparse

import httpx
from lxml import etree


def build_parser() -> argparse.ArgumentParser:
    """
    Builds the command-line argument parser.
    Called by: main()
    """
    parser = argparse.ArgumentParser(
        description="Transforms an inscription XML file with an XSL stylesheet from a path or URL.",
    )
    parser.add_argument(
        "--inscription-path",
        required=True,
        help="Path or URL to the source inscription XML file.",
    )
    parser.add_argument(
        "--stylesheet-path",
        required=True,
        help="Path or URL to the XSL stylesheet file.",
    )
    return parser


def read_text_file(file_path: Path) -> str:
    """
    Reads UTF-8 text from a filesystem path.
    Called by: read_text_source()
    """
    file_text = file_path.read_text(encoding="utf-8")
    return file_text


def is_url(value: str) -> bool:
    """
    Determines whether a string is an HTTP(S) URL.
    Called by: read_text_source()
    """
    parsed_value = urlparse(value)
    is_http_url = parsed_value.scheme in {"http", "https"} and parsed_value.netloc != ""
    return is_http_url


def read_text_url(url: str) -> str:
    """
    Reads UTF-8 text from an HTTP(S) URL.
    Called by: read_text_source()
    """
    with httpx.Client(follow_redirects=True, timeout=30.0) as client:
        response = client.get(url)
        response.raise_for_status()
        response_text = response.text
    return response_text


def read_text_source(source: str) -> str:
    """
    Reads UTF-8 text from either a filesystem path or an HTTP(S) URL.
    Called by: transform_xml()
    """
    if is_url(source):
        source_text = read_text_url(source)
    else:
        source_text = read_text_file(Path(source))
    return source_text


def transform_xml(inscription_path: str, stylesheet_path: str) -> str:
    """
    Applies an XSL transformation to an inscription XML document.
    Called by: main()
    """
    xml_text = read_text_source(inscription_path)
    xsl_text = read_text_source(stylesheet_path)
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


def get_lxml_version() -> str:
    """
    Inspects the runtime lxml version.
    Called by: main()
    """
    version_text = ".".join(str(part) for part in etree.LXML_VERSION)
    return version_text


def get_httpx_version() -> str:
    """
    Inspects the runtime httpx version.
    Called by: main()
    """
    version_text = httpx.__version__
    return version_text


def get_python_version() -> str:
    """
    Inspects the runtime Python version.
    Called by: main()
    """
    version_text = platform.python_version()
    return version_text


def main() -> None:
    """
    Parses arguments, runs the transformation, and prints the result.
    Called by: __main__
    """
    parser = build_parser()
    args = parser.parse_args()
    inscription_path = args.inscription_path
    stylesheet_path = args.stylesheet_path
    python_version = get_python_version()
    httpx_version = get_httpx_version()
    lxml_version = get_lxml_version()
    transformed_xml_text = transform_xml(inscription_path, stylesheet_path)
    print("\n" + f"(using python version: ``{python_version}``)")
    print(f"(using httpx version: ``{httpx_version}``)")
    print(f"(using lxml version: ``{lxml_version}``)" + "\n")
    print("=" * 35 + " transform-start " + "=" * 35)
    print(transformed_xml_text)
    print("=" * 35 + " transform-end " + "=" * 35 + "\n")


if __name__ == "__main__":
    main()
