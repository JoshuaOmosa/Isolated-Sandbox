# Threat: memory exhaustion. Expected verdict: OOM_KILLED.
# b"x" * n writes every byte, so the pages are really resident (a lazily
# zero-filled bytearray would not count against the cgroup limit).
hoard = []
while True:
    hoard.append(b"x" * 10_000_000)
