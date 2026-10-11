"""A project has one workspace owner, using only standard-library OS locks."""
from pathlib import Path
import os


class ProjectLease:
    def __init__(self, root):
        target = Path(root) / '.emu/workspace.lock'
        target.parent.mkdir(parents=True, exist_ok=True)
        self.stream = target.open('a+b')
        if target.stat().st_size == 0:
            self.stream.write(b'0'); self.stream.flush()
        self.stream.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.stream.close()
            raise ValueError('Project is already open in another workspace. Use its HTTP authoring API, or close that server before using the CLI.') from None

    def close(self):
        if self.stream.closed:
            return
        self.stream.seek(0)
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(self.stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(self.stream.fileno(), fcntl.LOCK_UN)
        self.stream.close()
