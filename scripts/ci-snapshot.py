"""Archive committable files without leaking host configuration or following links."""
import pathlib
import subprocess
import sys
import tarfile


def snapshot(output):
    names = subprocess.check_output([
        "git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"
    ]).decode().split("\0")
    with tarfile.open(output, "w") as archive:
        for name in sorted(set(names) - {""}):
            path = pathlib.Path(name)
            if path.is_absolute() or ".." in path.parts:
                raise ValueError("unsafe source path")
            if any(part == ".git" or (part.startswith(".env") and part != ".env.example")
                   for part in path.parts):
                raise ValueError("host configuration must not be tracked")
            if path.is_symlink():
                raise ValueError("CI snapshot does not accept symbolic links: " + name)
            if path.is_file():  # omit tracked files deleted in the working tree
                archive.add(path, arcname=name, recursive=False)


if __name__ == "__main__":
    snapshot(sys.argv[1])
