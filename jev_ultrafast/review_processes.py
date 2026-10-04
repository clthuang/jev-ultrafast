"""Precise local process birth identity for review child ownership checks."""

import ctypes
import errno
import os
import sys
from pathlib import Path


class BsdProcessInfo(ctypes.Structure):
    # Darwin PROC_PIDTBSDINFO includes the kernel's microsecond process birth time.
    _fields_ = [
        *[(name, ctypes.c_uint32) for name in (
            'flags', 'status', 'exit_status', 'pid', 'parent_pid', 'uid', 'gid', 'real_uid', 'real_gid',
            'saved_uid', 'saved_gid', 'reserved',
        )],
        ('command', ctypes.c_char * 16), ('name', ctypes.c_char * 32),
        *[(name, ctypes.c_uint32) for name in ('files', 'group', 'jobs', 'device', 'terminal_group')],
        ('nice', ctypes.c_int32), ('start_seconds', ctypes.c_uint64), ('start_microseconds', ctypes.c_uint64),
    ]


def process_identity(pid):
    if type(pid) is not int or pid <= 1:
        return {'state': 'unknown'}
    try:
        if sys.platform == 'darwin':
            library = ctypes.CDLL('/usr/lib/libproc.dylib', use_errno=True)
            read_info = library.proc_pidinfo
            read_info.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_uint64, ctypes.c_void_p, ctypes.c_int]
            info = BsdProcessInfo()
            ctypes.set_errno(0)
            if read_info(pid, 3, 0, ctypes.byref(info), ctypes.sizeof(info)) != ctypes.sizeof(info):
                return {'state': 'absent' if ctypes.get_errno() == errno.ESRCH else 'unknown'}
            if info.status == 5:
                return {'state': 'absent'}
            birth, uid, pgid = f'{info.start_seconds}:{info.start_microseconds}', info.uid, info.group
        elif sys.platform.startswith('linux'):
            path = Path(f'/proc/{pid}/stat')
            fields = path.read_text().rsplit(')', 1)[1].split()
            if fields[0] in {'Z', 'X'}:
                return {'state': 'absent'}
            birth, uid, pgid = fields[19], path.stat().st_uid, int(fields[2])
        else:
            return {'state': 'unknown'}
        if uid != os.getuid():
            return {'state': 'unknown'}
        return {'state': 'present', 'pid': pid, 'birth': birth, 'uid': uid, 'pgid': pgid}
    except FileNotFoundError:
        return {'state': 'absent'}
    except (OSError, ValueError, IndexError):
        return {'state': 'unknown'}
