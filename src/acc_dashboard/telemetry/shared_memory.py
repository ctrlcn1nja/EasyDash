from pyaccsharedmemory import accSharedMemory


class Telemetry:
    """Wrap ACC shared memory (or any telemetry source).

    Replace connect() with your actual shared-memory init code.
    """

    def __init__(self):
        self.sm = accSharedMemory()

    def connect(self):
        # TODO: initialize your ACC shared memory object here
        # self.sm = ...
        return self.sm

    def get_sm(self):
        return self.sm.read_shared_memory()
