========================
FHIR Shorthand Validator
========================


.. image:: https://img.shields.io/pypi/v/fsh-validator.svg
        :target: https://pypi.python.org/pypi/fsh-validator

.. image:: https://img.shields.io/travis/glichtner/fsh-validator.svg
        :target: https://travis-ci.com/glichtner/fsh-validator

.. image:: https://readthedocs.org/projects/fsh-validator/badge/?version=latest
        :target: https://fsh-validator.readthedocs.io/en/latest/?version=latest
        :alt: Documentation Status


.. image:: https://pyup.io/repos/github/glichtner/fsh-validator/shield.svg
     :target: https://pyup.io/repos/github/glichtner/fsh-validator/
     :alt: Updates



FHIR Shorthand Validator (fsh-validator) unshortens fsh input and validates all defined instances against their profiles.

fsh-validator is an interface to `SUSHI`_ and the `HL7 FHIR Validator`_ running the following workflow:

1. Run SUSHI to unshorten fsh files to structure definitions, instances, value sets etc.
2. Detect all defined profiles, valuesets and instances.
3. Validate all defined instances using the official HL7 FHIR Validator against their profiles.


For the full documentation see https://fsh-validator.readthedocs.io.

.. _SUSHI: https://github.com/FHIR/sushi
.. _`HL7 FHIR Validator`: https://confluence.hl7.org/display/FHIR/Using+the+FHIR+Validator

Quickstart
----------

Install the latest fsh-validator::

    pip install -U fsh-validator

Or directly from github repository::

    pip install -U git+https://github.com/glichtner/fsh-validator

Run fsh-validator in your fsh project path::

    $ fsh-validator --all


Parameters
----------

::

    usage: fsh-validator [-h] [--all] [--subdir SUBDIR] [--validator-path PATH_VALIDATOR] [--verbose] [--no-sushi] [--log-path LOG_PATH] [filename [filename ...]]

    positional arguments:
      filename              fsh file names (basename only - no path)

    optional arguments:
      -h, --help            show this help message and exit
      --all                 if set, all detected profiles will be validated
      --subdir SUBDIR       Specifies the subdirectory (relative to input/fsh/) in which to search for profiles if --all is set
      --validator-path PATH_VALIDATOR
                            path to validator
      --verbose             Be verbose
      --no-sushi            Do not run sushi before validating
      --log-path LOG_PATH   log file path - if supplied, log files will be written

Configuration
-------------

fsh-validator reads an optional configuration file ``.fsh-validator.yml`` in the base directory of the sushi project.
The configuration file currently supports the following parameters:

    exclude_code_systems:
        A list of code systems to exclude from validation. If an instance contains a code from a code system in this list,
        the instance will be skipped. This is useful to exclude code systems that are not yet supported by the validator
        or that may cause problems when validating (e.g. ICD-10-gm)
        The code systems are specified by their canonical URI.
        The default is to not exclude any code systems.

    exclude_resource_types:
        A list of resource types to exclude from validation. If an instance implements a resource of a type in this list,
        the instance will be skipped. This is useful to exclude resources that are not yet supported by the validator
        or that may cause problems when validating.
        The resource types are specified by their canonical name (e.g. "Bundle").
        The default is to not exclude any resource types.


Example configuration file:

.. code-block:: yaml

    exclude_code_systems:
        - http://hl7.org/fhir/sid/icd-10-cm
        - http://fhir.de/CodeSystem/bfarm/icd-10-gm

    exclude_resource_types:
        - Bundle
        - OperationOutcome

Examples
--------

**Example call to validate a *single* profile**

::

    $ cd ExampleIG/
    $ fsh-validator input/fsh/p-thoracic-drainage.fsh


**Example call to validate *all* profiles**

The following call validates all profiles in the subdirectory "vaccination/" and writes the results of the validation
log files in the directory logs/.

::

  $ cd ExampleIG/
  $ fsh-validator --all --subdir vaccination/ --log-path logs/


This is equivalent to calling::

    $ fsh-validator input/fsh/vaccination/*.fsh --log-path logs/


Credits
-------

This package was created with Cookiecutter_ and the `audreyr/cookiecutter-pypackage`_ project template.


.. _Cookiecutter: https://github.com/audreyr/cookiecutter
.. _`audreyr/cookiecutter-pypackage`: https://github.com/audreyr/cookiecutter-pypackage
