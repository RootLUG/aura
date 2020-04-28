import os
import tempfile
import tarfile
import zipfile
import mimetypes
from pathlib import Path
from dataclasses import dataclass
from typing import Generator, Union

import magic

from .rules import Rule
from ..uri_handlers.base import ScanLocation
from .. import config
from .. import utils


SUPPORTED_MIME = (
    "application/x-gzip",
    "application/gzip",
    "application/x-bzip2",
    "application/zip",
)

logger = config.get_logger(__name__)


@dataclass
class SuspiciousArchiveEntry(Rule):
    __hash__ = Rule.__hash__


@dataclass
class ArchiveAnomaly(Rule):
    __hash__ = Rule.__hash__

    @classmethod
    def from_generic_exception(cls, location: ScanLocation, exc: Exception):
        return cls(
            location = location.location,
            message="Could not open the archive for analysis",
            signature=f"archive_anomaly#read_error#{location.location}",
            score=config.get_score_or_default("corrupted-archive", 10),
            extra={
                "reason": "archive_read_error",
                "exc_message": exc.args[0],
                "exc_type": exc.__class__.__name__,
                "mime": location.metadata["mime"]
            },
        )


def is_suspicious(pth, location):
    norm = utils.normalize_path(pth)

    if pth.startswith("/"):
        return SuspiciousArchiveEntry(
            location=utils.normalize_path(location),
            signature=f"suspicious_archive_entry#absolute_path#{norm}#{location}",
            extra={"entry_type": "absolute_path", "entry_path": norm},
            score=config.get_score_or_default("suspicious-archive-entry-absolute-path", 50),
        )

    elif any(x == ".." for x in Path(pth).parts):
        return SuspiciousArchiveEntry(
            location=utils.normalize_path(location),
            signature=f"suspicious_archive_entry#parent_reference#{norm}#{location}",
            extra={"entry_type": "parent_reference", "entry_path": norm},
            score=config.get_score_or_default("suspicious-archive-entry-parent-reference", 50),
        )

    return None


def filter_zip(
    arch: zipfile.ZipFile, path, max_size=None
) -> Generator[Union[zipfile.ZipInfo, ArchiveAnomaly], None, None]:
    if max_size is None:
        max_size = config.get_maximum_archive_size()

    for x in arch.infolist():  # type: zipfile.ZipInfo
        pth = x.filename

        res = is_suspicious(x.filename, path)
        if res is not None:
            yield res
            continue
        elif max_size is not None and x.file_size > max_size:
            hit = ArchiveAnomaly(
                location=path,
                message="Archive contain a file that exceed the configured maximum size",
                signature=f"archive_anomaly#size#{path}#{pth}",
                extra={
                    "archive_path": pth,
                    "reason": "file_size_exceeded",
                    "size": x.file_size,
                    "limit": max_size
                },
            )
            yield hit
        else:
            yield x


def filter_tar(
    arch: tarfile.TarFile, path, max_size=None
) -> Generator[Union[tarfile.TarInfo, ArchiveAnomaly], None, None]:
    if max_size is None:
        config.get_maximum_archive_size()

    for member in arch.getmembers():
        pth = member.name

        res = is_suspicious(pth, path)
        if res is not None:
            yield res
        elif member.isdir():
            yield member
        elif member.issym() or member.islnk():
            # TODO: generate a hit
            # https://en.wikipedia.org/wiki/Tar_(computing)#Tarbomb
            continue
        elif member.isfile():
            if max_size is not None and member.size > max_size:
                hit = ArchiveAnomaly(
                    location=path,
                    message="Archive contain a file that exceed the configured maximum size",
                    score = config.get_score_or_default("archive-file-size-exceeded", 100),
                    signature=f"archive_anomaly#size#{path}#{pth}",
                    extra={
                        "archive_path": pth,
                        "reason": "file_size_exceeded",
                        "size": member.size,
                        "limit": max_size
                    },
                )
                yield hit
                continue
            else:
                yield member
        else:
            continue


def process_zipfile(path, tmp_dir) -> Generator[ArchiveAnomaly, None, None]:
    with zipfile.ZipFile(file=path, mode="r") as fd:
        for x in filter_zip(arch=fd, path=path):
            if isinstance(x, zipfile.ZipInfo):
                fd.extract(member=x, path=tmp_dir)
            else:
                yield x


def process_tarfile(path, tmp_dir) -> Generator[ArchiveAnomaly, None, None]:
    with tarfile.open(name=path, mode="r:*") as fd:
        for x in filter_tar(arch=fd, path=path):
            if isinstance(x, tarfile.TarInfo):
                fd.extract(member=x, path=tmp_dir, set_attrs=False)
            else:
                yield x


def archive_analyzer(*, location: ScanLocation, **kwargs):
    """
    Archive analyzer that looks for suspicious entries and unpacks the archive for recursive analysis
    """
    if location.location.is_dir():
        return

    mime = location.metadata["mime"]
    if mime not in SUPPORTED_MIME:
        return

    tmp_dir = tempfile.mkdtemp(prefix="aura_pkg__sandbox", suffix=os.path.basename(location.location))
    logger.info("Extracting to: '{}' [{}]".format(tmp_dir, mime))

    yield location.create_child(
        new_location=tmp_dir,
        cleanup=True,
    )

    try:
        if mime == "application/zip":
            yield from process_zipfile(path=location.location, tmp_dir=tmp_dir)
        elif mime in SUPPORTED_MIME:
            yield from process_tarfile(path=location.location, tmp_dir=tmp_dir)
        else:
            return
    except (tarfile.ReadError, zipfile.BadZipFile) as exc:
        yield ArchiveAnomaly.from_generic_exception(location, exc)


def diff_archive(diff):
    if diff.operation not in "RM":
        return
    elif diff.a_md5 == diff.b_md5:
        return

    a_scan_loc = diff.a_scan.create_child(diff.a_path)
    b_scan_loc = diff.b_scan.create_child(diff.b_path)

    a_hits = list(archive_analyzer(location=a_scan_loc))
    a_locations = [x for x in a_hits if type(x) == ScanLocation]
    a_hits = [x for x in a_hits if type(x) != ScanLocation]

    b_hits = list(archive_analyzer(location=b_scan_loc))
    b_locations = [x for x in b_hits if type(x) == ScanLocation]
    b_hits = [x for x in b_hits if type(x) != ScanLocation]

    # Yield all anomaly detections
    yield from a_hits
    yield from b_hits

    # Check if we should recurse diff into archives
    if len(a_locations) == 0 and len(b_locations) == 0:
        return

    # Create a new scan location
    new_a_location = a_locations[0] if a_locations else a_scan_loc
    new_b_location = b_locations[0] if b_locations else b_scan_loc
    new_a_location.metadata["b_scan_location"] = new_b_location
    yield new_a_location
