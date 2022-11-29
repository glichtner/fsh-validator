"""
Validate profiles and instances in a FSH file.

Process:
- Run SUSHI to generate JSON files (StructureDefinitions, ValueSets, Instances, etc) from FSH files
- Parse FSH file to identify profiles and instances defined in the file
- Run FHIR Java validator for each instance defined in FSH file
"""
import json
import re
import shutil
import subprocess  # nosec
import sys
import urllib.request
import warnings
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple, Union

import pandas as pd

# to raise exception when running the script if the package is not installed (required for saving logs to excel, md)
import tabulate  # type: ignore
import yaml
from jsonpath_ng.ext import parse

from .fshpath import FshPath

VALIDATOR_URL = "https://github.com/hapifhir/org.hl7.fhir.core/releases/latest/download/validator_cli.jar"
VALIDATOR_BASENAME = VALIDATOR_URL.split("/")[-1]


class bcolors:
    """Color strings for formatting console messages."""

    HEADER = "\033[95m"
    OKBLUE = "\033[94m"
    OKCYAN = "\033[96m"
    OKGREEN = "\033[92m"
    WARNING = "\033[93m"
    FAIL = "\033[91m"
    ENDC = "\033[0m"
    BOLD = "\033[1m"
    UNDERLINE = "\033[4m"


def print_box(
    message: str,
    min_length: int = 100,
    print_str: bool = True,
    col=bcolors.OKBLUE,
    border="=",
) -> str:
    """
    Print a string in a neat box.

    :param message: Message to be printed
    :param min_length: Minimum length of box (in characters)
    :param print_str: if False, the generated string will not be printed (just returned)
    :return: str to be printed if return_str is True
    """
    strlen = len(message)
    padding = " " * (min_length - strlen)
    message += padding

    s = [
        border * (max(min_length, strlen) + 4),
        f"* {message} *",
        border * (max(min_length, strlen) + 4),
    ]

    if print_str:
        for line in s:
            printc(line, col=col)

    return "\n".join(s)


class ValidatorExecutionException(Exception):
    pass


class ValidatorOutputParsingException(Exception):
    """Exception for errors in parsing validator output."""


class CommandNotSuccessfulException(Exception):
    """Shell command not successfully executed."""

    def __init__(
        self,
        msg: str = "Command execution not successful - see command output for more information",
        *args,
    ):
        """
        Shell command not successfully executed.

        :param msg: Message to display
        :param args: Other positional arguments for BaseException
        :param kwargs: Other keyword arguments for BaseException
        """
        args = tuple([msg] + list(args))
        super().__init__(*args)


class ValidatorStatus:
    """Status information of FHIR Validator run."""

    class Status(Enum):
        """Status of FHIR Validator run."""

        SUCCESS = "success"
        FAILURE = "failure"
        WARNING = "warning"
        NOT_RUN = "not-run"

    def __init__(
        self,
        output: Optional[str] = None,
        status: Status = Status.NOT_RUN,
        errors: Optional[List[str]] = None,
        warnings: Optional[List[str]] = None,
        profile: str = "",
        instance: str = "",
    ):
        """
        Status information of FHIR Validator run.

        :param output: Full validator output
        :param status: status string
        :param errors: list of errors during parsing
        :param warnings: list of warnings during parsing
        :param profile: name of profile against which validation was performed
        :param instance: name of instance that was validated
        """

        def list_if_none(v: Optional[List]) -> List:
            return [] if v is None else v

        self.status = status

        self.errors = list_if_none(errors)
        self.warnings: List[str] = list_if_none(warnings)
        self.notes: List[str] = []

        self.n_errors = len(self.errors)
        self.n_warnings = len(self.warnings)
        self.n_notes = len(self.notes)

        self.output = output

        self.profile = profile
        self.instance = instance
        self.instance_filename: Optional[str] = None

    @classmethod
    def parse(cls, output: str) -> "ValidatorStatus":
        """
        Parse FHIR Validator output.

        :param output: Output of a validator run
        :return: None
        """
        pattern_filename = re.compile(r"-- (.*) --{4,}\n")
        pattern_filename_single = re.compile(r"  Validate (.*)\n")
        pattern_status = re.compile(
            r"(?P<status>\*FAILURE\*|Success): (?P<n_errors>\d+) errors, (?P<n_warnings>\d+) warnings, (?P<n_notes>\d+) notes"
        )
        pattern_error = re.compile(r"  (Error @ .*)")
        pattern_warn = re.compile(r"  (Warning @ .*)")
        pattern_note = re.compile(r"  (Information @ .*)")

        self = cls(output=output)

        m = pattern_filename.search(output)
        if m is not None:
            self.instance_filename = m.group(1)
        else:
            matches = pattern_filename_single.findall(output)
            if matches is not None:
                if len(matches) > 1:
                    raise ValueError("Multiple filenames found in validator output")
                self.instance_filename = matches[0]
            else:
                raise ValueError("No filename found in validator output")

        m = pattern_status.search(output)

        status_map = {
            "Success": ValidatorStatus.Status.SUCCESS,
            "*FAILURE*": ValidatorStatus.Status.FAILURE,
        }

        self.status = status_map[m.group(1)]  # type: ignore
        self.n_errors, self.n_warnings, self.n_notes = (
            int(m.group(i + 2)) for i in range(3)  # type: ignore
        )
        self.errors = [m.group().strip() for m in pattern_error.finditer(output)]  # type: ignore
        self.warnings = [m.group().strip() for m in pattern_warn.finditer(output)]  # type: ignore
        self.notes = [m.group().strip() for m in pattern_note.finditer(output)]  # type: ignore

        if self.status == ValidatorStatus.Status.SUCCESS and len(self.warnings) > 0:
            self.status = ValidatorStatus.Status.WARNING

        return self

    def pretty_print(
        self, with_header: bool = False, with_instance: bool = False
    ) -> None:
        """
        Format and print the parsed output of fhir java validator to console.

        :param with_header: If true, print a header with information about the profile being validated
        :param with_instance: If true, print the name of the instance being validated
        :return: None
        """
        if with_header:
            print_box(f"Profile {self.profile}")

        if with_instance:
            print_box(f"Instance {self.instance}", border="-", col=bcolors.OKBLUE)

        if self.n_errors > 0:
            col = bcolors.FAIL
        elif self.n_warnings > 0:
            col = bcolors.WARNING
        else:
            col = bcolors.OKGREEN

        printc(
            f"{bcolors.BOLD}{self.status.value.title()}: {self.n_errors} errors, {self.n_warnings} warnings, {self.n_notes} notes",
            col,
        )

        for msg in self.errors:
            printc(f"  {msg}", bcolors.FAIL)

        for msg in self.warnings:
            printc(f"  {msg}", bcolors.WARNING)

        for msg in self.notes:
            print(f"  {msg}")

        sys.stdout.flush()

    def failed(self):
        """
        Check if the validation run failed.

        :return: True if the validation run failed, False otherwise
        """
        return self.status == ValidatorStatus.Status.FAILURE

    def to_frame(self) -> pd.DataFrame:
        """
        Get status as pandas DataFrame.

        :return: Status as DataFrame
        """
        return pd.DataFrame(
            dict(
                status=self.status,
                n_errors=self.n_errors,
                n_warnings=self.n_warnings,
                n_notes=self.n_notes,
                instance=self.instance,
                profile=self.profile,
            ),
            index=[0],
        )


class ValidatorStatusParser:
    @staticmethod
    def parse(output: str) -> List[ValidatorStatus]:
        outputs = re.split("\n-{4,}", output, flags=re.MULTILINE)

        results: List[ValidatorStatus] = []

        for output in outputs:
            if output.strip() == "":
                continue
            result = ValidatorStatus.parse(output)
            if result is not None:
                results.append(result)

        return results


def download_validator(fname_validator: Path) -> None:
    """
    Download FHIR Java validator.

    :param fname_validator: Filename where the validator will be downloaded to
    :return: None
    """
    urllib.request.urlretrieve(VALIDATOR_URL, fname_validator)  # nosec


def parse_fsh(fname_fsh: Path) -> Tuple[List[Dict], List[Dict]]:
    """
    Parse FSH file to extract profiles and instances that are defined in it.

    :param fname_fsh: Filename of the FSH file to parse
    :return: List of defined profiles, List of defined instances
    """
    with open(fname_fsh) as f:
        content = f.read()

    re_group_capture = r"[a-zA-Z0-9_\-\$]+"

    pattern = re.compile(
        rf"Profile: (?P<profile>{re_group_capture})[^\n]*\nParent: (?P<parent>{re_group_capture})[^\n]*\nId: (?P<id>{re_group_capture})",
        re.MULTILINE,
    )
    fsh_profiles = [m.groupdict() for m in pattern.finditer(content)]

    pattern = re.compile(
        rf"Instance: (?P<instance>{re_group_capture})[^\n]*\nInstanceOf: (?P<instanceof>{re_group_capture})",
        re.MULTILINE,
    )
    fsh_instances = [m.groupdict() for m in pattern.finditer(content)]

    return fsh_profiles, fsh_instances


def parse_fsh_generated(path: Path) -> Tuple[Dict, Dict, Dict, Dict, Dict, Dict]:
    """
    Parse json files generated from FSH through SUSHI.

    Goal: Extract structure definitions, instances, value set and dependencies from generated JSON files.

    :param path: Path to generated files through SUSHI
    :return: StructureDefinitions, Instances, Dependencies, ValueSets, CodeSystems, Extensions
    """

    def parse_structure_definition(fname: Path, json_data: str) -> Tuple[Dict, str]:
        url = parse("$.url").find(json_data)[0].value
        type = parse("$.type").find(json_data)[0].value
        base = parse("$.baseDefinition").find(json_data)[0].value
        abstract = parse("$.abstract").find(json_data)[0].value
        profilesAdditional = [
            x.value[0]
            for x in parse("$.differential.element[*].type[*].profile").find(json_data)
        ]

        return {
            url: {
                "filename": fname.resolve(),
                "id": parse("$.id").find(json_data)[0].value,
                "type": type,
                "base": base,
                "profilesAdditional": profilesAdditional,
                "abstract": abstract,
            }
        }, type

    def parse_instance(fname: Path, json_data: str) -> Dict:

        resourceType = parse("$.resourceType").find(json_data)[0].value
        codeSystems = {s.value for s in parse("$.*.coding[*].system").find(json_data)}
        profile = parse("$.meta.profile").find(json_data)
        if len(profile) == 0:
            profile = resourceType
            explicit_profile = False
        else:
            profile = profile[0].value[0]
            explicit_profile = True

        profilesAdditional = []
        if resourceType == "Bundle":
            # need to also load all sub profiles from entries in case of Bundle resource
            profilesAdditional = [
                p.value[0]
                for p in parse("$.entry[*].resource.meta.profile").find(json_data)
            ]

        return {
            parse("$.id")
            .find(json_data)[0]
            .value: {
                "filename": fname.resolve(),
                "profile": profile,
                "explicitProfile": explicit_profile,
                "resourceType": resourceType,
                "codeSystems": codeSystems,
                "profilesAdditional": profilesAdditional,
            }
        }

    def parse_ig(fname: Path, json_data: str) -> Dict:
        deps = parse("$.dependsOn[*]").find(json_data)
        return {v.value["packageId"]: v.value for v in deps}

    def parse_value_set(fname: Path, json_data: str) -> Dict:
        url = parse("$.url").find(json_data)[0].value
        return {
            url: {
                "filename": fname.resolve(),
                "id": parse("$.id").find(json_data)[0].value,
            }
        }

    def parse_code_system(fname: Path, json_data: str) -> Dict:
        url = parse("$.url").find(json_data)[0].value
        return {
            url: {
                "filename": fname.resolve(),
                "id": parse("$.id").find(json_data)[0].value,
            }
        }

    sdefs = {}
    instances = {}
    deps = {}
    vs = {}
    cs = {}
    extensions = {}

    for fname in path.glob("*.json"):
        json_data = json.load(open(fname))
        resourceType = parse("$.resourceType").find(json_data)[0].value

        if resourceType == "StructureDefinition":
            sd, type = parse_structure_definition(fname, json_data)
            if type == "Extension":
                extensions.update(sd)
            else:
                sdefs.update(sd)
        elif resourceType == "ImplementationGuide":
            deps.update(parse_ig(fname, json_data))
        elif resourceType == "ValueSet":
            vs.update(parse_value_set(fname, json_data))
        elif resourceType == "CodeSystem":
            cs.update(parse_code_system(fname, json_data))
        else:
            instances.update(parse_instance(fname, json_data))

    return sdefs, instances, deps, vs, cs, extensions


def get_paths(base_path: Union[str, Path]) -> Tuple[Path, Path]:
    """
    Get fsh input and output paths from base path.

    :param base_path: Base path
    :return: FSH input path, FSH output path
    """
    return (
        Path(base_path) / "input" / "fsh",
        Path(base_path) / "fsh-generated" / "resources",
    )


def get_fsh_base_path(path: Union[str, Path]) -> Path:
    """
    Get the base path of an FSH project given a filename or path.

    FSH files in sushi projects are located in the subfolder "input/fsh/". This method returns the parent of this base
    path, if available, or throws an exception

    :param path: Base to get fsh base path from
    :return: FSH project base path
    """
    path = Path(path).absolute()

    if (path / "input" / "fsh").exists():
        return path

    for i in range(len(path.parts) - 1):
        if path.parts[i] == "input" and path.parts[i + 1] == "fsh":
            return Path(*path.parts[:i]).absolute()

    raise ValueError(f'Could not find fsh input path (input/fsh/) in "{path}"')


def deduplicate_obi_codes(fname: Path) -> None:
    """
    Remove duplicate http://terminology.hl7.org/CodeSystem/v2-0203#OBI codes from an instance.

    When using the Medizininformatik Initiative Profile LabObservation, SUSHI v2.1.1 inserts the identifier.type code
    for http://terminology.hl7.org/CodeSystem/v2-0203#OBI twice, but it has a cardinality of 1, resulting in an error
    by the FHIR validator. This workaround function actively removes the duplicates.

    MII Profile: https://www.medizininformatik-initiative.de/fhir/core/modul-labor/StructureDefinition/ObservationLab

    :param fname: Filename of instance to remove duplicates from
    :return: None
    """

    def num_obi_codes(json_data: Dict):
        jp = parse(
            "$.type.coding[?code = 'OBI' & system='http://terminology.hl7.org/CodeSystem/v2-0203']"
        )
        return len(jp.find(json_data))

    def del_obi_codes(identifier: Dict):
        codings = identifier["type"]["coding"]
        for i, coding in enumerate(codings):
            if (
                coding["system"] == "http://terminology.hl7.org/CodeSystem/v2-0203"
                and coding["code"] == "OBI"
            ):
                del codings[i]
                break

    json_data = json.load(open(fname))

    if "identifier" not in json_data:
        return

    for identifier in json_data["identifier"]:
        if num_obi_codes(identifier) > 1:
            warnings.warn(f"Found multiple OBI codes in {fname}, removing")
            del_obi_codes(identifier)

    json.dump(json_data, open(fname, "w"), indent=2)


def get_abstract_profile_ids(sdefs: Dict[str, Dict]) -> Set[str]:
    """
    Get all abstract profile IDs from a set of StructureDefinitions.

    :param sdefs: StructureDefinitions to get abstract profile IDs from
    :return: Set of abstract profile IDs
    """
    return {v["id"] for v in sdefs.values() if v["abstract"]}


def _validate_fsh_files(
    ig_id: str,
    path_output: Path,
    fnames: List[Path],
    fname_validator: str,
    fhir_version: str,
    exclude_code_systems: Optional[Set] = None,
    exclude_resource_types: Optional[Set] = None,
    verbose: bool = False,
) -> List[ValidatorStatus]:
    """
    Validate FSH files.

    Process:
    - Extract Profiles and Instances defined in each FSH file
    - Run FHIR Java validator for each instance to validate it against its corresponding profile

    :param path_output: output path (of SUSHI project)
    :param fnames: FSH file names to validate (full paths)
    :param fname_validator: full path to FHIR Java validator file
    :param fhir_version: FHIR version to use in validator
    :param exclude_code_systems: Optional set of code systems which prevent instances from being validated
    :param exclude_resource_types: Optional set of resource types which prevent instances from being validated
    :param verbose: Print more information
    :return: ValidatorStatus objects
    """
    sdefs, instances, deps, vs, cs, extensions = parse_fsh_generated(path_output)

    # Workaround for duplicate OBI codes in instances from profile MII laboratory observation
    for k, v in instances.items():
        deduplicate_obi_codes(v["filename"])

    results = []
    fsh_instances_cleaned = []

    for i, fname in enumerate(fnames):

        if not fname.exists():
            raise FileNotFoundError(fname)

        fsh_profiles, fsh_instances = parse_fsh(fname)
        # percent = (i + 1) / len(fnames) * 100
        # print(
        #    f"[{percent: 5.1f}%] Processing file {fname} with {len(fsh_profiles)} profiles and {len(fsh_instances)} instances ({i+1}/{len(fnames)})"
        # )
        profiles_without_instance = check_instances_availability(
            fsh_profiles, fsh_instances, get_abstract_profile_ids(sdefs)
        )

        if len(profiles_without_instance):
            for p in profiles_without_instance:
                status = ValidatorStatus(
                    status=ValidatorStatus.Status.FAILURE,
                    errors=[f"No instances defined for profile {p}"],
                    profile=p,
                )
                status.pretty_print(with_header=True)
                results.append(status)
            continue

        for fsh_instance in fsh_instances:
            instance = instances[fsh_instance["instance"]]
            if exclude_code_systems is not None and any(
                cs in exclude_code_systems for cs in instance["codeSystems"]
            ):
                status = ValidatorStatus(
                    status=ValidatorStatus.Status.WARNING,
                    warnings=[
                        f"Skipped instance {fsh_instance['instance']} due to excluded code system(s) used in the instance"
                    ],
                    profile=fsh_instance["instanceof"],
                )
                status.pretty_print(with_header=True)
                results.append(status)
            elif (
                exclude_resource_types is not None
                and instance["resourceType"] in exclude_resource_types
            ):
                status = ValidatorStatus(
                    status=ValidatorStatus.Status.WARNING,
                    warnings=[
                        f"Skipped instance {fsh_instance['instance']} due to excluded resource type {instance['resourceType']}"
                    ],
                    profile=fsh_instance["instanceof"],
                )
                status.pretty_print(with_header=True)
                results.append(status)
            else:

                fsh_instances_cleaned.append(
                    {
                        "instance": fsh_instance["instance"],
                        "instanceof": fsh_instance["instanceof"],
                        "filename": instance["filename"],
                        "profile": instance["profile"],
                        "explicit-profile": instance["explicitProfile"],
                    }
                )

    ig_fname = path_output / f"ImplementationGuide-{ig_id}.json"
    df = pd.DataFrame(fsh_instances_cleaned)

    df.loc[df["explicit-profile"], "profile"] = None

    for profile, instances_validation in df.groupby("profile", dropna=False):
        run_validation(
            fname_validator=fname_validator,
            ig_fname=str(ig_fname),
            profile=profile,
            instances=instances_validation,
            deps=deps,
            fhir_version=fhir_version,
            verbose=verbose,
        )

    return results


def validate_fsh(
    fsh_filenames: List[FshPath],
    fname_validator: str,
    fhir_version: str,
    exclude_code_systems: Optional[Set] = None,
    exclude_resource_types: Optional[Set] = None,
    verbose: bool = False,
) -> List[ValidatorStatus]:
    """
    Validate specific fsh files.

    Process:
    - Extract Profiles and Instances defined in FSH file
    - Run FHIR Java validator for each instance to validate it against its corresponding profile

    :param fsh_filename: FSH file names
    :param fname_validator: Full path to FHIR Java validator file
    :param fhir_version: FHIR version to use in validator
    :param exclude_code_systems: Optional set of code systems which prevent instances from being validated
    :param exclude_resource_types: Optional set of resource types which prevent instances from being validated
    :param verbose: Print more information
    :return: List of validation status, full output and instance and profile names
    """
    # We assume that the base path is consistent across all files
    base_path = fsh_filenames[0].fsh_base_path()
    _, path_output = get_paths(base_path)

    return _validate_fsh_files(
        ig_id=get_parameter_from_sushi_config(base_path, "id"),
        path_output=path_output,
        fnames=[f.absolute() for f in fsh_filenames],
        fname_validator=fname_validator,
        fhir_version=fhir_version,
        exclude_code_systems=exclude_code_systems,
        exclude_resource_types=exclude_resource_types,
        verbose=verbose,
    )


def validate_all_fsh(
    base_path: Path,
    subdir: str,
    fname_validator: str,
    fhir_version: str,
    exclude_code_systems: Optional[Set] = None,
    exclude_resource_types: Optional[Set] = None,
    verbose: bool = False,
) -> List[ValidatorStatus]:
    """
    Validate all FSH files in a given subdir.

    Process:
    - Extract Profiles and Instances defined in FSH file
    - Run FHIR Java validator for each instance to validate it against its corresponding profile

    :param base_path: base path (of SUSHI project)
    :param subdir: subdirectory of profiles
    :param fname_validator: full path to FHIR Java validator file
    :param fhir_version: FHIR version to use in validator
    :param verbose: Print more information
    :param exclude_code_systems: Optional set of code systems which prevent instances from being validated
    :param exclude_resource_types: Optional set of resource types which prevent instances from being validated
    :return: List of validation status, full output and instance and profile names
    """
    path_input, path_output = get_paths(base_path)

    path_full = path_input / subdir

    if not path_full.exists():
        raise FileNotFoundError(path_full)

    fnames = list(path_full.rglob("*.fsh"))

    sys.stdout.flush()

    return _validate_fsh_files(
        ig_id=get_parameter_from_sushi_config(base_path, "id"),
        path_output=path_output,
        fnames=fnames,
        fname_validator=fname_validator,
        fhir_version=fhir_version,
        exclude_code_systems=exclude_code_systems,
        exclude_resource_types=exclude_resource_types,
        verbose=verbose,
    )


def check_instances_availability(
    fsh_profiles: List[Dict], fsh_instances: List[Dict], abstract_profiles: Set[str]
) -> List[str]:
    """
    Check if at least one instance exists for each defined profile extracted from FSH file.

    :param fsh_profiles: List of profile defined in FSH file
    :param fsh_instances: List of instances defined in FSH file
    :param abstract_profiles: Set of abstract profiles
    :return: List of profiles without instances
    """
    profiles_without_instance = []

    for p in fsh_profiles:
        if p["id"] in abstract_profiles:
            continue

        if not any(i["instanceof"] == p["id"] for i in fsh_instances):
            profiles_without_instance.append(p["id"])

    return profiles_without_instance


def get_profile_chain(sdefs: Dict, profile: str) -> List[str]:
    """
    Get a list of all profiles that a specific profile is based on and that are part of this SUSHI project.

    The objective of this function to provide a list of all parent profiles of a specific profile for inclusion as
    parameters to the FHIR validator.

    :param sdefs: StructureDefinitions from SUSHI output
    :param profile: Profile name to get all parents profiles of
    :return: List of all parent profiles of supplied profile name (including the profile itself)
    """
    res: List[str] = []

    def _traverse(profile, res):
        res.append(profile)
        if sdefs[profile]["base"] in sdefs:
            _traverse(sdefs[profile]["base"], res)

    _traverse(profile, res)

    return res


def get_profiles_to_include(sdefs, instance):
    """
    Get a list of all profiles that a specific instance is based on and that are part of this SUSHI project.

    :param sdefs: StructureDefinitions from SUSHI output
    :param instance: Instance name to get all parents profiles of
    :return: List of all parent profiles of supplied instance name (including the instance itself)
    """
    profiles_processed = []

    if instance["resourceType"] == "Bundle":
        profiles_queue = [instance["profile"]] + instance["profilesAdditional"]
    else:
        profiles_queue = [instance["profile"]]

    profiles_to_include = []

    for profile in profiles_queue:
        if profile in profiles_processed:
            continue
        profiles_processed.append(profile)

        if profile in sdefs:
            profiles_queue += [
                p
                for p in sdefs[profile]["profilesAdditional"]
                if p not in profiles_processed
            ]

            profile_chain = get_profile_chain(sdefs, profile)
            profiles_to_include += profile_chain

    profiles_to_include = set(profiles_to_include)
    return profiles_to_include


def run_validation(
    fname_validator: str,
    ig_fname: str,
    profile: Optional[str],
    instances: pd.DataFrame,
    deps: Dict,
    fhir_version: str,
    verbose: bool,
) -> List[ValidatorStatus]:
    """
    Run FHIR Java validator for each instance defined in FSH file.

    :param fname_validator: full path to FHIR Java validator file
    :param ig_fname: full path to IG file
    :param profile: profile name
    :param instances: Instance from SUSHI output
    :param deps: Dependencies from SUSHI output
    :param fhir_version: FHIR version to use in validator
    :param verbose: Print more information
    :return: List of validation result dicts containing validation status, full output and instance and profile names
    """
    cmd_base = [
        "java",
        f"-jar {fname_validator}",
        f"-version {fhir_version}",
        "-txLog logs/txlog.html",
    ]
    cmd_base += [f'-ig {dep["packageId"]}#{dep["version"]}' for dep in deps.values()]

    cmd = list(cmd_base)
    cmd += [f"-ig {ig_fname}"]
    if not pd.isnull(profile):
        cmd += [f"-profile {profile}"]
    cmd += [str(f) for f in instances["filename"].to_list()]

    if not pd.isnull(profile):
        print_box(f"Validating instances against profile {profile}")
    else:
        print_box("Validating instances against all profiles")

    try:
        status = execute_validator(cmd, verbose=verbose)
    except ValidatorExecutionException:
        error = ValidatorStatus(
            status=ValidatorStatus.Status.FAILURE, errors=["popen failed"]
        )
        error.pretty_print()
        return [error]
    except ValidatorOutputParsingException as e:
        print("Could not parse validator output:", flush=True)
        print(str(e), flush=True)
        return [
            ValidatorStatus(
                status=ValidatorStatus.Status.FAILURE,
                errors=["Error during validator execution"],
                output=str(e),
            )
        ]

    for s, (_, instance) in zip(status, instances.iterrows()):
        assert s.instance_filename == str(
            instance["filename"]
        ), "Status and instance filename do not match"
        s.instance = instance["instance"]
        s.profile = instance["profile"]
        s.pretty_print(with_instance=True)

    return status


def run_command(cmd: Union[str, List[str]]) -> None:
    """
    Run a shell command.

    Raises CommandNotSuccessfulException if the return code of the command is not 0.

    :param cmd: Command to run as single string or list of strings
    :return: None
    """
    if isinstance(cmd, list):
        cmd = "  ".join([str(s) for s in cmd])

    c = subprocess.run(cmd, shell=True)  # nosec

    if c.returncode != 0:
        raise CommandNotSuccessfulException()


def printc(msg: str, col: str, end: str = "\n") -> None:
    """
    Print a message in color to console.

    :param msg: Message to print
    :param col: Color (from bcolors)
    :param end: end of line character(s)
    :return: None
    """
    print(f"{col}{msg}{bcolors.ENDC}", end=end, flush=True)


def execute_validator(
    cmd: Union[str, List[str]], verbose: bool = False
) -> List[ValidatorStatus]:
    """
    Execute the Java FHIR validator and parse it's output.

    :param cmd: Command to execute
    :param verbose: If true, all output from the validator will be printed to stdout.
    :return: ValidatorStatus object
    """
    if isinstance(cmd, list):
        cmd = "  ".join([str(s) for s in cmd])

    if verbose:
        print(cmd)

    popen = subprocess.Popen(  # nosec
        cmd, stdout=subprocess.PIPE, universal_newlines=True, shell=True
    )

    if popen.stdout is None:
        raise ValidatorExecutionException("Could not get stdout from validator")

    output = []

    for line in popen.stdout:
        if verbose or line.strip() in ["Loading", "Validating"]:
            printc(line, col=bcolors.HEADER, end="")
            sys.stdout.flush()

        output.append(line)
    popen.stdout.close()
    popen.wait()

    output_s = "".join(output)

    try:
        status = ValidatorStatusParser.parse(output_s)
    except Exception:
        raise ValidatorOutputParsingException(output_s)

    return status


def store_log(results: List[ValidatorStatus], log_path: Path) -> None:
    """
    Store parsed and full output from validator run to files.

    Parsed output will be saved to an excel file in tabular format, full output to a text file.

    :param results: List of ValidatorStatus objects as returned by _validate_fsh_files()
    :param log_path: Path where log files are stored
    :return: None
    """
    dfs = []
    output = ""

    for status in results:
        dfs.append(status.to_frame())

        if status.instance != "":
            output += print_box(
                f"Validating {status.instance} on profile {status.profile}",
                print_str=False,
            )
        else:
            output += print_box(f"Profile {status.profile}", print_str=False)

        if status.output is not None:
            output += status.output
        output += "\n\n"

    df = pd.concat([s.to_frame() for s in results]).reset_index(drop=True)

    log_basename = "validation_" + datetime.now().strftime("%y%m%dT%H%M%S")

    with open(log_path / (log_basename + ".log"), "w") as f:
        f.write(output)

    df.to_excel(log_path / (log_basename + ".xlsx"), index=False)
    df.to_markdown(log_path / (log_basename + ".md"), index=False)


def get_parameter_from_sushi_config(base_path: Path, parameter: str) -> str:
    """
    Get a parameter from the SUSHI config file.

    :param base_path: Path to the SUSHI config file
    :param parameter: Parameter to get
    :return: FHIR version string
    """
    conf_filename = base_path / "sushi-config.yaml"
    if not conf_filename.exists():
        raise FileNotFoundError(f"Could not find {conf_filename}")

    with open(conf_filename) as f:
        conf = yaml.safe_load(f)
        value = conf[parameter]

    return value


def assert_sushi_installed() -> None:
    """
    Assert that FSH Sushi is an executable on the system.

    :return: None
    """
    if shutil.which("sushi") is None:
        raise FileNotFoundError(
            'Could not detect fsh sushi on the system. Install via "npm install -g fsh-sushi".'
        )


def run_sushi(path: str) -> None:
    """
    Run SUSHI to convert FSH files.

    :param path: Path to run SUSHI in
    :return: None
    """
    assert_sushi_installed()

    run_command(f"sushi {path}")
