"""Explicit preparation, local serving, and reproducible offline evaluation."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from archsearch.config import DEFAULT_HOME
from archsearch.corpus import CorpusError, load_corpus
from archsearch.index import IndexUnavailable, prepare_index


def main() -> None:
    parser = argparse.ArgumentParser(prog="archsearch", description="古迹语义检索与地图")
    parser.add_argument("--home", type=Path, default=DEFAULT_HOME, help="模型、索引与报告目录")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("prepare", help="联网下载固定版本模型并构建本地索引")
    serve = commands.add_parser("serve", help="只加载本地资源，启动网页及 API")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    evaluate = commands.add_parser("evaluate", help="输出中英查询的排名、耗时及已标注指标")
    evaluate.add_argument("--qrels", type=Path, help="人工确认的相关性标注 JSON")
    evaluate.add_argument(
        "--output", type=Path, help="报告 JSON 文件，默认 HOME/reports/evaluation.json"
    )
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            result = prepare_index(load_corpus(), args.home)
            print(json.dumps({"ready": True, "count": len(result["site_ids"])}, ensure_ascii=False))
        elif args.command == "serve":
            os.environ["HF_HUB_OFFLINE"] = "1"
            import uvicorn

            from archsearch.api import create_app

            uvicorn.run(create_app(args.home), host=args.host, port=args.port)
        else:
            from archsearch.evaluation import evaluate_corpus

            report = evaluate_corpus(
                args.home, args.output or args.home / "reports" / "evaluation.json", args.qrels
            )
            print(json.dumps(report, ensure_ascii=False, indent=2))
    except (CorpusError, IndexUnavailable, ValueError, OSError) as error:
        print(f"ArchSearch: {error}", file=sys.stderr)
        raise SystemExit(1) from error
