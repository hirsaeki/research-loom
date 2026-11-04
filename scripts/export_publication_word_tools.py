"""Export inert Word helpers from a verified Publication preview; never install/run them."""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    from plugins.local_application import LocalApplicationFacade
    from plugins.local_application.publication.word_tools import export_word_tools

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--build-id", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    with LocalApplicationFacade.open_workspace(args.workspace) as facade:
        preview = facade.show_publication_preview(args.build_id)
    print(json.dumps(export_word_tools(preview, args.output), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
