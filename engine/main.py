#!/usr/bin/env python3
import argparse
import json
import sys
from audio import inspect, merge, stop_children
from ordering import order


def emit(value):
    print(json.dumps(value, ensure_ascii=False), flush=True)


def main():
    parser = argparse.ArgumentParser(description='Smart Audio Merge engine')
    subs = parser.add_subparsers(dest='command', required=True)
    plan = subs.add_parser('plan')
    plan.add_argument('files', nargs='+')
    run = subs.add_parser('merge')
    run.add_argument('--output', required=True)
    run.add_argument('--keep-order', action='store_true')
    run.add_argument('files', nargs='+')
    args = parser.parse_args()
    try:
        items = inspect(args.files)
        if args.command == 'plan':
            emit(order(items))
        else:
            if not args.keep_order:
                items = order(items)['items']
            merge(items, args.output, emit)
    except KeyboardInterrupt:
        emit({'event': 'cancelled', 'message': 'Merge cancelled. Source files are preserved.'})
        return 130
    except Exception as error:
        emit({'event': 'error', 'message': str(error)})
        return 1
    finally:
        stop_children()
    return 0


if __name__ == '__main__':
    sys.exit(main())
