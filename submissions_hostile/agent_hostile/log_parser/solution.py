# Threat: fork bomb. The pids limit refuses new processes; the wall-clock ceiling
# (or the memory cap) ends the run. Expected verdict: TIMEOUT or OOM_KILLED.
import os

while True:
    try:
        os.fork()
    except OSError:
        pass
