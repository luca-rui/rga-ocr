"""Stand-in for the adapter in the rga config of the tests that stop a
search half-way: leaves a file named after its process id in the directory
named by ADAPTER_PIDS, then sleeps for a minute and prints nothing."""
import os
import time

open(os.path.join(os.environ["ADAPTER_PIDS"], str(os.getpid())), "w").close()
time.sleep(60)
