"""Small durable file primitives. Domain locks belong to the caller."""

import contextlib
import json
import os
import tempfile
from pathlib import Path


class PublicationUncertain(OSError):
    """A publish was attempted; inspect authoritative storage before repeating work."""


def canonical_bytes(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode('utf-8')


def fsync_directory(directory):
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def publish(path, value, *, immutable=False):
    """Flush a unique same-directory temporary, publish, then sync the directory.

    Callers serialize mutable replacements. Immutable publication uses link's exclusive
    destination creation, so even another writer cannot replace an existing artifact.
    """
    path = Path(path)
    encoded = canonical_bytes(value) + b'\n'
    descriptor, temporary = tempfile.mkstemp(prefix=f'.{path.name}.', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            if immutable:
                os.link(temporary, path)
            else:
                os.replace(temporary, path)
            fsync_directory(path.parent)
        except OSError as error:
            raise PublicationUncertain('Publication requires storage verification') from error
    finally:
        with contextlib.suppress(OSError):
            os.unlink(temporary)
    return path
