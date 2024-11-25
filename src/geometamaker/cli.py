import argparse
import logging
import pprint
import sys

import geometamaker

def main(user_args=None):
    parser = argparse.ArgumentParser(
        description=(
            ''),
        prog='geometamaker'
    )

    subparsers = parser.add_subparsers(dest='subcommand')
    describe_subparser = subparsers.add_parser(
        'describe', help='describe a dataset')
    describe_subparser.add_argument(
        'filepath',
        help=('path to a dataset to describe'))

    args = parser.parse_args(user_args)

    root_logger = logging.getLogger()
    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter(
        fmt='%(asctime)s %(name)-18s %(levelname)-8s %(message)s',
        datefmt='%m/%d/%Y %H:%M:%S ')
    handler.setFormatter(formatter)
    handler.setLevel(logging.DEBUG)  # TODO: take user input

    if args.subcommand == 'describe':
        description = geometamaker.describe(args.filepath).write()
        sys.stdout.write(pprint.pformat(description))
        parser.exit()

if __name__ == '__main__':
    main()
