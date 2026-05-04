global filename 
filename = "error"
DEBUG = False

def debug_print(*args, **kwargs):
    """Always checks the current DEBUG flag, so importers never get a stale binding."""
    if DEBUG:
        print(*args, **kwargs)
