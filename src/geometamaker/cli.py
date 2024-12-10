import argparse
import logging
import os
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
    validate_subparser = subparsers.add_parser(
        'validate', help='validate a metadata document')
    validate_subparser.add_argument(
        'filepath',
        help=('path to a metadata document, or directory containing documents, to validate'))
    validate_subparser.add_argument(
        '-r', '--recursive', action='store_true', default=False,
        help='recurse through subdirectories in search of metadata documents.')

    args = parser.parse_args(user_args)

    # root_logger = logging.getLogger()
    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter(
        fmt='%(asctime)s %(name)-18s %(levelname)-8s %(message)s',
        datefmt='%m/%d/%Y %H:%M:%S ')
    handler.setFormatter(formatter)
    handler.setLevel(logging.DEBUG)  # TODO: take user input

    if args.subcommand == 'describe':
        if os.path.isdir(args.filepath):
            geometamaker.describe_dir(
                args.filepath, recursive=args.recursive)
        else:
            geometamaker.describe(args.filepath).write()
        # sys.stdout.write(pprint.pformat(description))
        parser.exit()

    if args.subcommand == 'validate':
        if os.path.isdir(args.filepath):
            file_list, message_list = geometamaker.validate_dir(
                args.filepath, recursive=args.recursive)
            for filepath, msg in zip(file_list, message_list):
                sys.stdout.write(f'{filepath}: {msg}\n')
        else:
            validation_message = geometamaker.validate(args.filepath)
            if validation_message:
                sys.stdout.write(validation_message)
        parser.exit()


if __name__ == '__main__':
    main()
