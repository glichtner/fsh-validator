"""FSH file paths representations."""
from typing import Union, Tuple, Optional
from pathlib import Path


class FshPath:
    """FSH file paths representations."""

    def __init__(self, filename: Union[str, Path]):
        """
        FSH file paths representations.

        The SUSHI folder structure consists of the base path, where e.g. the configuration sushi-config.yaml are located,
        and the input/fsh/ subdirectory, where all fsh files are stored that are processed by SUSHI. This class helps locating
        the base path and the actual filename of fsh files.

        :param filename: FSH filename (or path)
        """
        self._path = Path(filename)
        if not self.exists():
            raise ValueError(f'File "{filename}" does not exist.')

        self._fsh_base_path, self._fsh_name = self.fsh_parts()

    def fsh_parts(self) -> Tuple[Path, Optional[Path]]:
        """
        Process a filename into the fsh base path (without input/fsh/) and the fsh filename relative to input/fsh/.

        :return: Tuple of base path (without input/fsh/) and filename (relative to input/fsh/ folder)
        """
        path = self._path.absolute()
        fsh_name = None

        if (path / "input" / "fsh").exists():
            fsh_base_path = path
        elif path.parts[-1] == "input" and (path / "fsh").exists():
            fsh_base_path = Path(*path.parts[:-1])
        else:
            for i in range(len(path.parts) - 1):
                if path.parts[i] == "input" and path.parts[i + 1] == "fsh":
                    fsh_base_path = Path(*path.parts[:i]).absolute()
                    fsh_name = Path(*path.parts[(i + 2) :])

        if fsh_base_path is None:
            raise ValueError(f'Could not find fsh input path (input/fsh/) in "{path}".')

        return fsh_base_path, fsh_name

    def fsh_base_path(self) -> Path:
        """
        Get the FSH base path (without input/fsh/).

        :return: FSH base path (without input/fsh/)
        """
        return self._fsh_base_path

    def fsh_name(self) -> Optional[Path]:
        """
        Get the FSH filename (relative to input/fsh/).

        :return: FSH filename (relative to input/fsh/)
        """
        return self._fsh_name

    def exists(self) -> bool:
        """
        Return whether the file represented by this class exists.

        :return: True if file exists, False otherwise
        """
        return self._path.exists()

    def absolute(self) -> Path:
        """
        Resolve relative to absolute path.

        :return: Absolute filename
        """
        return self._path.absolute()

    def __str__(self) -> str:
        """
        Return full filename as string.

        :return: Full filename as string.
        """
        return str(self._path)

    def __repr__(self) -> str:
        """
        Return class string representation.

        :return: class string representation
        """
        return self.__class__.__name__ + "('" + str(self) + "')"
