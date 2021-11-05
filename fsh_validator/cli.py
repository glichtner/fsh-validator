"""Command line interface for fsh-validator."""
import os
import sys
import argparse
from pathlib import Path
from .fsh_validator import (
    print_box,
    run_sushi,
    validate_all_fsh,
    validate_fsh,
    download_validator,
    bcolors,
    VALIDATOR_BASENAME,
    store_log,
    assert_sushi_installed,
    get_fsh_base_path,
    get_fhir_version_from_sushi_config,
)
from .fshpath import FshPath


def main():
    """
    fsh-validator command line interface main.

    :return: None
    """
    parser = argparse.ArgumentParser(
        description="Validate a fsh file",
        formatter_class=argparse.RawTextHelpFormatter,
    )

    arg_fname = parser.add_argument(
        "filename", help="fsh file names (basename only - no path)", nargs="*"
    )

    parser.add_argument(
        "--all",
        dest="all",
        action="store_true",
        help="if set, all detected profiles will be validated",
        required=False,
        default=False,
    )

    parser.add_argument(
        "--subdir",
        dest="subdir",
        type=str,
        help="Specifies the subdirectory (relative to input/fsh/) in which to search for profiles if --all is set",
        required=False,
        default="",
    )

    parser.add_argument(
        "--validator-path",
        dest="path_validator",
        type=str,
        help="path to validator",
        required=False,
        default=None,
    )

    parser.add_argument(
        "--verbose",
        dest="verbose",
        action="store_true",
        help="Be verbose",
        required=False,
        default=False,
    )

    parser.add_argument(
        "--no-sushi",
        dest="no_sushi",
        action="store_true",
        help="Do not run sushi before validating",
        required=False,
        default=False,
    )

    parser.add_argument(
        "--log-path",
        dest="log_path",
        type=str,
        help="log file path - if supplied, log files will be written",
        required=False,
        default=None,
    )

    args = parser.parse_args()

    if not args.all and len(args.filename) == 0:
        raise argparse.ArgumentError(
            arg_fname, "filename must be set if --all is not specified"
        )
    elif args.all and len(args.filename) == 0:
        # Use current working dir as input path
        filenames = [FshPath(os.getcwd())]
    else:
        filenames = [FshPath(filename) for filename in args.filename]

    base_paths = set(filename.fsh_base_path() for filename in filenames)
    if len(base_paths) > 1:
        raise ValueError(
            "Found multiple base paths for fsh project, expecting exactly one"
        )
    base_path = base_paths.pop()

    validator_path = (
        args.path_validator if args.path_validator is not None else base_path
    )
    fname_validator = Path(validator_path) / VALIDATOR_BASENAME
    if not fname_validator.exists():
        print_box("Downloading java validator")
        download_validator(fname_validator.resolve())

    if not args.no_sushi:
        print_box("Running SUSHI")
        run_sushi(base_path)

    fhir_version = get_fhir_version_from_sushi_config(base_path)

    if args.all:
        print_box("Validating all FSH files")
        results = validate_all_fsh(
            base_path,
            args.subdir,
            str(fname_validator),
            verbose=args.verbose,
            fhir_version=fhir_version,
        )
    else:
        print_box("Validating FSH files")
        results = validate_fsh(
            filenames,
            str(fname_validator),
            verbose=args.verbose,
            fhir_version=fhir_version,
        )

    if args.log_path is not None:
        log_path = Path(args.log_path)
        if not log_path.exists():
            log_path.mkdir()
        store_log(results, log_path)

    if any([r.status != "Success" for r in results]):
        print_box("Errors during profile validation", col=bcolors.FAIL)
        sys.exit(1)
    else:
        print_box("All profiles successfully validated", col=bcolors.OKGREEN)
        sys.exit(0)


if __name__ == "__main__":
    main()
