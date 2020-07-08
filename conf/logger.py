import logging
import pathlib

dir_path = str(pathlib.Path().absolute())

# LOGGER STUFF
logger = logging.getLogger('REL')
logger.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s',datefmt='%m/%d/%Y %I:%M:%S %p')
ch = logging.StreamHandler()
fh = logging.FileHandler(dir_path + '/logs.log')
ch.setLevel(logging.DEBUG)
fh.setLevel(logging.INFO)
ch.setFormatter(formatter)
fh.setFormatter(formatter)
logger.addHandler(ch)
logger.addHandler(fh)