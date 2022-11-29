#!/usr/bin/env python

"""The setup script."""

from typing import List

from setuptools import find_packages, setup

with open("README.rst") as readme_file:
    readme = readme_file.read()

with open("HISTORY.rst") as history_file:
    history = history_file.read()

requirements: List[str] = [
    "jsonpath_ng>=1.5.3",
    "pandas>=1.2.4",
    "openpyxl>=3.0.9",
    "tabulate>=0.8.9",
    "pyyaml>=5.4.1",
]

test_requirements: List[str] = []

setup(
    author="Gregor Lichtner",
    python_requires=">=3.6",
    classifiers=[
        "Development Status :: 2 - Pre-Alpha",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: BSD License",
        "Natural Language :: English",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.6",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
    ],
    description="FHIR Shorthand Validator unshortens fsh input and validates all defined instances against their profiles.",
    entry_points={
        "console_scripts": [
            "fsh-validator=fsh_validator.__main__:main",
        ],
    },
    install_requires=requirements,
    license="BSD license",
    long_description=readme + "\n\n" + history,
    include_package_data=True,
    keywords="fsh-validator",
    name="fsh-validator",
    packages=find_packages(include=["fsh_validator", "fsh_validator.*"]),
    test_suite="tests",
    tests_require=test_requirements,
    url="https://github.com/glichtner/fsh-validator",
    version="0.3.0",
    zip_safe=False,
)
