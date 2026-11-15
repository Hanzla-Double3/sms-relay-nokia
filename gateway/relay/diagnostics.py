"""Payload-free structured diagnostics; dedicated logger never includes request headers."""
import json
import logging
import sys

logger=logging.getLogger('relay.diagnostics')
if not logger.handlers:
    handler=logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter('%(message)s'))
    logger.addHandler(handler)
logger.setLevel(logging.INFO)
logger.propagate=False

def emit(record):
    logger.info(json.dumps(record,separators=(',',':')))
