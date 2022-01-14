""" A tool to cache fimfarchive epubs and fimfiction html chapters as text.

The cached txt chapters will be written to FIMFARCHIVE_PATH/txt.
The downloaded html chapters will be written to FIMFARCHIVE_PATH/html.

Single-threaded usage:
    python -m cache_chapters 1 1

Multi-threaded usage:
    CORES=$(cat /proc/cpuinfo | grep processor | wc -l)
    seq $CORES | xargs -L1 -P$CORES python -m cache_chapters $CORES

When running with multiple threads, the script will stagger the start times
to avoid spiking memory usage. All of the threads will start within 5 minutes.

"""

UNPACKED_FIMFARCHIVE_PATH = '/archives/ppp-clone/story-data'


import fimfarchive
import template
import sys
import time
import random

num_cores = int(sys.argv[1])
id = int(sys.argv[2])

if num_cores > 1:
    time.sleep(random.random() * 300)

ff = fimfarchive.Fimfarchive(UNPACKED_FIMFARCHIVE_PATH)

for story_id in ff.stories_by_id.keys():
    if int(story_id) % num_cores == id:
        ff.cache_chapters(story_id)
