# Holds all custom exceptions
#

from common.logger import logger


# -------------------------------- Exceptions -------------------------------- #

class DataHandlerError(Exception):
    def __init__(self, message):
        logger.debug(message)
